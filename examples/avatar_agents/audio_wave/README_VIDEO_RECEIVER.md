# DataStream视频接收器和发送器

本目录包含用于通过LiveKit DataStream接收和发送视频流的实现。这些实现参考了相应的音频接收器/发送器实现，并进行了适当的修改以支持视频流。

## 文件说明

- `video_receiver.py`: 包含 `DataStreamVideoReceiver` 和 `DataStreamVideoOutput` 类的实现
- `video_receiver_example.py`: 演示如何使用 `DataStreamVideoReceiver` 接收视频流
- `video_sender_example.py`: 演示如何使用 `DataStreamVideoOutput` 发送视频流

## 主要类

### VideoSegmentEnd

标记视频段结束的简单标记类。

### VideoReceiver

抽象基类，定义了视频接收器的核心接口。

### DataStreamVideoReceiver

通过LiveKit DataStream从发送者接收流式视频的实现。如果提供了sender_identity，则订阅指定的参与者；如果没有提供，则订阅房间中的第一个agent参与者。

主要方法:
- `start()`: 启动接收器，连接到目标参与者
- `notify_playback_finished()`: 通知发送者播放已完成
- `__aiter__()`: 作为异步迭代器使用，持续输出视频帧或VideoSegmentEnd

### DataStreamVideoOutput

使用LiveKit DataStream将视频流式传输到远程接收器的实现。

主要方法:
- `send_frame()`: 发送视频帧到远程接收器
- `flush()`: 标记当前视频段的结束
- `clear_buffer()`: 清除缓冲区
- `add_playback_finished_listener()`: 添加播放完成事件的监听器

## 如何运行示例

### 准备工作

1. 确保安装了LiveKit相关的Python包：
   ```
   pip install livekit
   ```

2. 对于视频发送者示例，还需要安装NumPy：
   ```
   pip install numpy
   ```

### 运行视频接收器示例

```bash
python video_receiver_example.py --url wss://your-livekit-server.com --token YOUR_TOKEN --room ROOM_NAME
```

### 运行视频发送器示例

```bash
python video_sender_example.py --url wss://your-livekit-server.com --token YOUR_TOKEN --destination RECEIVER_IDENTITY --room ROOM_NAME
```

## 使用示例

### 接收视频

```python
from video_receiver import DataStreamVideoReceiver, VideoSegmentEnd

# 初始化视频接收器
video_receiver = DataStreamVideoReceiver(room)

# 启动视频接收器
await video_receiver.start()

# 处理接收到的视频帧
async for frame in video_receiver:
    if isinstance(frame, VideoSegmentEnd):
        print("视频段结束")
        continue
        
    # 处理视频帧
    print(f"接收到视频帧，大小: {frame.width}x{frame.height}")
    
    # 使用视频帧（例如，传递给视频源）
    video_source.capture_frame(frame)
```

### 发送视频

```python
from video_receiver import DataStreamVideoOutput

# 初始化视频输出
video_output = DataStreamVideoOutput(
    room,
    destination_identity="target-participant-id",
    width=640,
    height=480
)

# 添加播放完成事件的监听器
def on_playback_finished(playback_position, interrupted):
    print(f"播放完成: 位置={playback_position:.2f}秒, 中断={interrupted}")
    
video_output.add_playback_finished_listener(on_playback_finished)

# 发送视频帧
for i in range(100):
    # 创建一个视频帧（示例）
    video_frame = create_video_frame()  # 你需要实现此函数
    
    # 发送帧
    await video_output.send_frame(video_frame)
    
# 标记视频段结束
video_output.flush()
```

## 注意事项

1. 确保LiveKit服务器配置正确，并且有效的token包含适当的权限。
2. 视频接收器和发送器需要在同一个LiveKit房间中才能通信。
3. 对于生产环境，建议增加错误处理和重试逻辑。 