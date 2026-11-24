from __future__ import annotations

import asyncio
import contextlib
import threading


class StreamServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self._queues: set[asyncio.Queue[bytes]] = set()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.Server | None = None
        self._started = threading.Event()
        self._running = False

    @property
    def client_count(self) -> int:
        return len(self._queues)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._started.clear()
        self._thread = threading.Thread(target=self._run_loop, name="curlcast-server", daemon=True)
        self._thread.start()
        self._started.wait(timeout=5.0)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def _main() -> None:
            server = await asyncio.start_server(self._handle_client, self.host, self.port)
            self._server = server
            self._started.set()
            try:
                async with server:
                    await server.serve_forever()
            except (asyncio.CancelledError, Exception):
                pass

        try:
            loop.run_until_complete(_main())
        except (asyncio.CancelledError, RuntimeError):
            pass
        finally:
            with contextlib.suppress(Exception):
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending and not loop.is_closed():
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.read(1024)
            headers = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Cache-Control: no-cache, no-transform\r\n"
                b"Connection: close\r\n"
                b"Access-Control-Allow-Origin: *\r\n\r\n"
                b"\x1b[2J\x1b[H\x1b[?25l"
            )
            writer.write(headers)
            await writer.drain()

            q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4)
            self._queues.add(q)
            try:
                while self._running:
                    chunk = await q.get()
                    writer.write(chunk)
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass
            finally:
                self._queues.discard(q)
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    def broadcast_frame(self, frame_text: str) -> None:
        if not self._running or not self._queues or self._loop is None:
            return
        data = f"\x1b[H{frame_text}".encode()

        def _dispatch() -> None:
            for q in list(self._queues):
                if q.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        q.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(data)

        self._loop.call_soon_threadsafe(_dispatch)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._server is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._server.close)
            for q in list(self._queues):
                with contextlib.suppress(Exception):
                    q.put_nowait(b"")
            self._queues.clear()
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
            self._thread = None
        self._loop = None
        self._server = None
