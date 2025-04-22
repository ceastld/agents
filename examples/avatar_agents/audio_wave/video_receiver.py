from __future__ import annotations

import asyncio
import ctypes
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import asdict, dataclass
from typing import Literal, Optional

from livekit import rtc
from livekit.agents import utils

# 定义一个视频数据段结束的标志类
class VideoSegmentEnd:
    pass

# 创建VideoReceiver抽象基类
class VideoReceiver(rtc.EventEmitter[Literal["clear_buffer"]]):
    async def start(self) -> None:
        pass

    def notify_playback_finished(
        self, playback_position: float, interrupted: bool
    ) -> None | asyncio.coroutine:
        """通知发送者播放已完成"""
        pass

    def __aiter__(self) -> AsyncIterator[rtc.VideoFrame | VideoSegmentEnd]:
        """持续输出视频帧或者当流结束时输出VideoSegmentEnd"""
        pass

# 定义播放完成事件数据类
@dataclass
class PlaybackFinishedEvent:
    playback_position: float
    interrupted: bool

# 定义常量
RPC_CLEAR_BUFFER = "lk.clear_buffer_video"
RPC_PLAYBACK_FINISHED = "lk.playback_finished_video"
VIDEO_STREAM_TOPIC = "lk.video_stream"

logger = logging.getLogger("avatar-example")

class DataStreamVideoReceiver(VideoReceiver):
    """
    视频接收器，通过LiveKit DataStream从发送者接收流式视频。
    如果提供了sender_identity，则订阅指定的参与者。
    如果没有提供，则订阅房间中的第一个agent参与者。
    """

    def __init__(self, room: rtc.Room, *, sender_identity: str | None = None):
        super().__init__()
        self._room = room
        self._sender_identity = sender_identity
        self._remote_participant: rtc.RemoteParticipant | None = None

        self._stream_readers: list[rtc.ByteStreamReader] = []
        self._stream_reader_changed: asyncio.Event = asyncio.Event()

        self._current_reader: rtc.ByteStreamReader | None = None
        self._current_reader_cleared: bool = False

    async def start(self) -> None:
        # 等待目标参与者或第一个agent参与者加入
        self._remote_participant = await self._wait_for_participant(identity=self._sender_identity)

        def _handle_clear_buffer(data: rtc.RpcInvocationData) -> str:
            assert self._remote_participant is not None
            if data.caller_identity != self._remote_participant.identity:
                logger.warning(
                    "clear buffer event received from unexpected participant",
                    extra={
                        "caller_identity": data.caller_identity,
                        "expected_identity": self._remote_participant.identity,
                    },
                )
                return "reject"

            if self._current_reader:
                self._current_reader_cleared = True
            self.emit("clear_buffer")
            return "ok"

        self._room.local_participant.register_rpc_method(RPC_CLEAR_BUFFER, _handle_clear_buffer)

        def _handle_stream_received(
            reader: rtc.ByteStreamReader, remote_participant_id: str
        ) -> None:
            if remote_participant_id != self._remote_participant.identity:
                return

            self._stream_readers.append(reader)
            self._stream_reader_changed.set()

        self._room.register_byte_stream_handler(VIDEO_STREAM_TOPIC, _handle_stream_received)

    async def notify_playback_finished(self, playback_position: float, interrupted: bool) -> None:
        """通知发送者播放已完成"""
        assert self._remote_participant is not None
        event = PlaybackFinishedEvent(playback_position=playback_position, interrupted=interrupted)
        try:
            logger.debug(
                f"notifying video playback finished: {event.playback_position:.3f}s, "
                f"interrupted: {event.interrupted}"
            )
            await self._room.local_participant.perform_rpc(
                destination_identity=self._remote_participant.identity,
                method=RPC_PLAYBACK_FINISHED,
                payload=json.dumps(asdict(event)),
            )
        except Exception as e:
            logger.exception(f"error notifying video playback finished: {e}")

    def __aiter__(self) -> AsyncIterator[rtc.VideoFrame | VideoSegmentEnd]:
        return self._stream_impl()

    @utils.log_exceptions(logger=logger)
    async def _stream_impl(
        self,
    ) -> AsyncGenerator[rtc.VideoFrame | VideoSegmentEnd, None]:
        while True:
            await self._stream_reader_changed.wait()

            while self._stream_readers:
                self._current_reader = self._stream_readers.pop(0)
                width = int(self._current_reader.info.attributes.get("width", "640"))
                height = int(self._current_reader.info.attributes.get("height", "480"))
                video_type = int(self._current_reader.info.attributes.get("type", 
                                 str(rtc.VideoBufferType.RGBA.value)))
                
                async for data in self._current_reader:
                    if self._current_reader_cleared:
                        # 如果清除缓冲区被调用，忽略当前读取器的剩余数据
                        continue
                    
                    frame = rtc.VideoFrame(
                        width=width,
                        height=height,
                        type=rtc.VideoBufferType(video_type),
                        data=data,
                    )
                    yield frame
                
                self._current_reader = None
                self._current_reader_cleared = False
                yield VideoSegmentEnd()

            self._stream_reader_changed.clear()

    async def _wait_for_participant(self, identity: str | None = None) -> rtc.RemoteParticipant:
        """等待参与者加入房间并返回"""

        def _is_matching_participant(participant: rtc.RemoteParticipant) -> bool:
            if identity is not None and participant.identity != identity:
                return False
            return participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT

        for participant in self._room.remote_participants.values():
            if _is_matching_participant(participant):
                return participant

        fut = asyncio.Future[rtc.RemoteParticipant]()

        def _handle_participant_connected(participant: rtc.RemoteParticipant) -> None:
            if _is_matching_participant(participant):
                fut.set_result(participant)

        self._room.on("participant_connected", _handle_participant_connected)
        try:
            return await fut
        finally:
            self._room.off("participant_connected", _handle_participant_connected)


class DataStreamVideoOutput:
    """
    使用LiveKit DataStream将视频流式传输到远程头像工作器的视频输出实现。
    """

    def __init__(
        self, room: rtc.Room, *, destination_identity: str, 
        width: int = 640, height: int = 480,
        video_type: rtc.VideoBufferType = rtc.VideoBufferType.RGBA
    ):
        self._room = room
        self._destination_identity = destination_identity
        self._width = width
        self._height = height
        self._video_type = video_type
        self._stream_writer: rtc.ByteStreamWriter | None = None
        self._pushed_frames: int = 0
        self._tasks: set[asyncio.Task] = set()

        # 播放完成处理器
        def _handle_playback_finished(data: rtc.RpcInvocationData) -> str:
            if data.caller_identity != self._destination_identity:
                logger.warning(
                    "video playback finished event received from unexpected participant",
                    extra={
                        "caller_identity": data.caller_identity,
                        "expected_identity": self._destination_identity,
                    },
                )
                return "reject"

            event = PlaybackFinishedEvent(**json.loads(data.payload))
            self.on_playback_finished(
                playback_position=event.playback_position,
                interrupted=event.interrupted,
            )
            return "ok"

        self._room.local_participant.register_rpc_method(
            RPC_PLAYBACK_FINISHED, _handle_playback_finished
        )
        
        # 定义事件回调
        self._playback_finished_callbacks = []

    def on_playback_finished(self, playback_position: float, interrupted: bool) -> None:
        """播放完成事件回调"""
        for callback in self._playback_finished_callbacks:
            callback(playback_position, interrupted)

    def add_playback_finished_listener(self, callback) -> None:
        """添加播放完成监听器"""
        self._playback_finished_callbacks.append(callback)
        
    def remove_playback_finished_listener(self, callback) -> None:
        """移除播放完成监听器"""
        if callback in self._playback_finished_callbacks:
            self._playback_finished_callbacks.remove(callback)

    async def send_frame(self, frame: rtc.VideoFrame) -> None:
        """发送视频帧到远程工作器"""
        if not self._stream_writer:
            self._stream_writer = await self._room.local_participant.stream_bytes(
                name=utils.shortuuid("VIDEO_"),
                topic=VIDEO_STREAM_TOPIC,
                destination_identities=[self._destination_identity],
                attributes={
                    "width": str(frame.width),
                    "height": str(frame.height),
                    "type": str(frame.type.value),
                },
            )
            self._pushed_frames = 0
        await self._stream_writer.write(bytes(frame.data))
        self._pushed_frames += 1

    def flush(self) -> None:
        """标记当前视频段的结束"""
        if self._stream_writer is None:
            return

        # 关闭流，标记段结束
        task = asyncio.create_task(self._stream_writer.aclose())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        self._stream_writer = None
        logger.debug(
            "data stream video sink flushed",
            extra={"pushed_frames": self._pushed_frames},
        )
        self._pushed_frames = 0

    def clear_buffer(self) -> None:
        """清除缓冲区"""
        task = asyncio.create_task(
            self._room.local_participant.perform_rpc(
                destination_identity=self._destination_identity,
                method=RPC_CLEAR_BUFFER,
                payload="",
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard) 