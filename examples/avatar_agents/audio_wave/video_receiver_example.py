import asyncio
import logging
import sys
from pathlib import Path

from livekit import rtc

# 添加当前目录到系统路径，以便导入本地模块
sys.path.insert(0, str(Path(__file__).parent))
from video_receiver import DataStreamVideoReceiver, VideoSegmentEnd

# 设置日志格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("video-receiver-example")

async def main(room: rtc.Room):
    """视频接收器示例的主要逻辑"""
    try:
        # 初始化视频接收器
        video_receiver = DataStreamVideoReceiver(room)
        
        # 启动视频接收器
        await video_receiver.start()
        logger.info("视频接收器已启动，等待视频数据...")
        
        # 创建视频源用于发布
        video_source = rtc.VideoSource()
        video_track = rtc.LocalVideoTrack.create_video_track("received_video", video_source)
        
        # 发布视频轨道
        video_options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
        publication = await room.local_participant.publish_track(video_track, video_options)
        logger.info(f"视频轨道已发布: {publication.track.sid}")
        
        # 处理视频帧
        frame_count = 0
        total_frames = 0
        segment_count = 0
        
        async for frame in video_receiver:
            if isinstance(frame, VideoSegmentEnd):
                logger.info(f"视频段 #{segment_count} 结束，共接收 {frame_count} 帧")
                segment_count += 1
                frame_count = 0
                # 通知发送方播放完成
                await video_receiver.notify_playback_finished(
                    playback_position=total_frames / 30.0,  # 假设30fps
                    interrupted=False
                )
                continue
                
            # 处理视频帧
            frame_count += 1
            total_frames += 1
            logger.info(f"接收到视频帧 #{frame_count}，大小: {frame.width}x{frame.height}")
            
            # 将接收到的视频帧推送到视频源
            video_source.capture_frame(frame)

    except Exception as e:
        logger.error(f"发生错误: {e}", exc_info=True)
    finally:
        logger.info("视频接收器示例结束")

async def run_service(url: str, token: str):
    """运行视频接收器服务"""
    room = rtc.Room()
    try:
        # 连接到LiveKit房间
        logger.info(f"正在连接到 {url}")
        await room.connect(url, token)
        logger.info(f"已连接到房间 {room.name}")

        # 运行主应用逻辑
        await main(room)
    except rtc.ConnectError as e:
        logger.error(f"连接到房间失败: {e}")
        raise
    finally:
        await room.disconnect()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="视频接收器示例")
    parser.add_argument("--url", required=True, help="LiveKit服务器URL")
    parser.add_argument("--token", required=True, help="加入房间的Token")
    parser.add_argument("--room", help="房间名称")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    args = parser.parse_args()

    # 设置日志级别
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format=f"[{args.room or ''}] %(asctime)s - %(levelname)s - %(message)s",
    )

    try:
        asyncio.run(run_service(args.url, args.token))
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    except Exception as e:
        logger.error(f"致命错误: {e}")
        sys.exit(1)
    finally:
        logger.info("已关闭") 