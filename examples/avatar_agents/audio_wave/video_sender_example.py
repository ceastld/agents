import asyncio
import logging
import sys
import time
import numpy as np
from pathlib import Path

from livekit import rtc

# 添加当前目录到系统路径，以便导入本地模块
sys.path.insert(0, str(Path(__file__).parent))
from video_receiver import DataStreamVideoOutput

# 设置日志格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("video-sender-example")

class SimpleAnimationGenerator:
    """生成简单动画的类，用于测试视频发送"""
    
    def __init__(self, width: int = 640, height: int = 480, fps: float = 30.0):
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_interval = 1.0 / fps
        
    async def generate_frames(self, num_frames: int = 300):
        """生成指定数量的动画帧"""
        for i in range(num_frames):
            # 创建一个随时间变化的简单动画（彩色波动图案）
            t = i / 30.0  # 时间参数
            
            # 创建RGBA图像数组
            image = np.zeros((self.height, self.width, 4), dtype=np.uint8)
            
            # 生成彩色波动图案
            for y in range(self.height):
                for x in range(self.width):
                    r = int(127 + 127 * np.sin(x / 30 + t))
                    g = int(127 + 127 * np.sin(y / 20 + t * 0.7))
                    b = int(127 + 127 * np.sin((x + y) / 40 + t * 1.3))
                    image[y, x, 0] = r
                    image[y, x, 1] = g
                    image[y, x, 2] = b
                    image[y, x, 3] = 255  # 完全不透明
            
            # 在图像上添加帧号
            if i % 10 == 0:
                # 简单文本显示（这里只是用一个白色方块表示）
                x_pos = 20
                y_pos = 20
                size = 40
                image[y_pos:y_pos+size, x_pos:x_pos+size] = [255, 255, 255, 255]
            
            # 创建视频帧
            video_frame = rtc.VideoFrame(
                width=self.width,
                height=self.height,
                type=rtc.VideoBufferType.RGBA,
                data=image.tobytes()
            )
            
            yield video_frame
            
            # 控制帧率
            await asyncio.sleep(self.frame_interval)

async def main(room: rtc.Room, destination_identity: str):
    """视频发送者示例的主要逻辑"""
    try:
        # 初始化视频输出
        video_output = DataStreamVideoOutput(
            room,
            destination_identity=destination_identity,
            width=640,
            height=480
        )
        
        # 添加回调来处理播放完成事件
        def on_playback_finished(playback_position: float, interrupted: bool):
            logger.info(f"收到播放完成通知: 位置={playback_position:.2f}秒, 中断={interrupted}")
            
        video_output.add_playback_finished_listener(on_playback_finished)
        
        # 创建动画生成器
        animation_gen = SimpleAnimationGenerator(width=640, height=480, fps=30.0)
        
        # 发送两个视频段，每段150帧
        for segment in range(2):
            logger.info(f"开始发送视频段 #{segment}")
            frame_count = 0
            
            # 生成并发送视频帧
            async for frame in animation_gen.generate_frames(num_frames=150):
                await video_output.send_frame(frame)
                frame_count += 1
                
                if frame_count % 30 == 0:
                    logger.info(f"已发送 {frame_count} 帧")
            
            # 标记视频段结束
            video_output.flush()
            logger.info(f"视频段 #{segment} 发送完成，共 {frame_count} 帧")
            
            # 在两个段之间暂停一下
            await asyncio.sleep(1.0)
        
        # 等待最后的播放完成通知
        await asyncio.sleep(5.0)
        
    except Exception as e:
        logger.error(f"发生错误: {e}", exc_info=True)
    finally:
        logger.info("视频发送者示例结束")

async def run_service(url: str, token: str, destination_identity: str):
    """运行视频发送者服务"""
    room = rtc.Room()
    try:
        # 连接到LiveKit房间
        logger.info(f"正在连接到 {url}")
        await room.connect(url, token)
        logger.info(f"已连接到房间 {room.name}")
        
        # 等待目标参与者加入
        if destination_identity:
            participant_found = False
            for participant in room.remote_participants.values():
                if participant.identity == destination_identity:
                    logger.info(f"找到目标参与者: {destination_identity}")
                    participant_found = True
                    break
            
            if not participant_found:
                logger.info(f"等待目标参与者加入: {destination_identity}")
                event = asyncio.Event()
                
                def on_participant_connected(p):
                    if p.identity == destination_identity:
                        logger.info(f"目标参与者已加入: {p.identity}")
                        event.set()
                
                room.on("participant_connected", on_participant_connected)
                await event.wait()
                room.off("participant_connected", on_participant_connected)

        # 运行主应用逻辑
        await main(room, destination_identity)
    except rtc.ConnectError as e:
        logger.error(f"连接到房间失败: {e}")
        raise
    finally:
        await room.disconnect()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="视频发送者示例")
    parser.add_argument("--url", required=True, help="LiveKit服务器URL")
    parser.add_argument("--token", required=True, help="加入房间的Token")
    parser.add_argument("--destination", required=True, help="目标接收者的身份标识")
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
        asyncio.run(run_service(args.url, args.token, args.destination))
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    except Exception as e:
        logger.error(f"致命错误: {e}")
        sys.exit(1)
    finally:
        logger.info("已关闭") 