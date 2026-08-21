import asyncio
import websockets

async def run():
    uri = "ws://127.0.0.1:8765"
    async with websockets.connect(uri, max_size=None) as ws:
        for i in range(5):
            data = await ws.recv()
            print(f"Frame {i+1}: {len(data)} bytes = {len(data)//4} amostras int32")

asyncio.run(run())