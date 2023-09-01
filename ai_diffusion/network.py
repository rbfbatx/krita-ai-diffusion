import asyncio
import json
from typing import NamedTuple, Callable
from PyQt5.QtCore import QByteArray, QUrl
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply


class NetworkError(Exception):
    def __init__(self, code, msg, url):
        self.code = code
        self.message = msg
        self.url = url
        super().__init__(self, msg)

    def __str__(self):
        return self.message

    @staticmethod
    def from_reply(reply: QNetworkReply):
        code = reply.error()
        url = reply.url().toString()
        try:  # extract detailed information from the payload
            data = json.loads(reply.readAll().data())
            error = data.get("error", "")
            if error != "":
                return NetworkError(code, f"{error} ({reply.errorString()})", url)
        except:
            pass
        return NetworkError(code, reply.errorString(), url)


class OutOfMemoryError(NetworkError):
    def __init__(self, code, msg, url):
        super().__init__(code, msg, url)


class Interrupted(Exception):
    def __init__(self):
        super().__init__(self, "Operation cancelled")


class Disconnected(Exception):
    def __init__(self):
        super().__init__(self, "Disconnected")


class Request(NamedTuple):
    url: str
    future: asyncio.Future


class RequestManager:
    def __init__(self):
        self._net = QNetworkAccessManager()
        self._net.finished.connect(self._finished)
        self._requests = {}

    def http(self, method, url: str, data: dict = None):
        self._cleanup()

        request = QNetworkRequest(QUrl(f"http://{url}"))
        # request.setTransferTimeout({"GET": 30000, "POST": 0}[method]) # requires Qt 5.15 (Krita 5.2)
        if data is not None:
            data_bytes = QByteArray(json.dumps(data).encode("utf-8"))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            request.setHeader(QNetworkRequest.ContentLengthHeader, data_bytes.size())

        assert method in ["GET", "POST"]
        if method == "POST":
            reply = self._net.post(request, data_bytes)
        else:
            reply = self._net.get(request)

        future = asyncio.get_running_loop().create_future()
        self._requests[reply] = Request(url, future)
        return future

    def get(self, url: str):
        return self.http("GET", url)

    def post(self, url: str, data: dict):
        return self.http("POST", url, data)

    def _finished(self, reply: QNetworkReply):
        try:
            code = reply.error()
            future = self._requests[reply].future
            if future.cancelled():
                return  # operation was cancelled, discard result
            if code == QNetworkReply.NoError:
                content_type = reply.header(QNetworkRequest.ContentTypeHeader)
                data = reply.readAll().data()
                if "application/json" in content_type:
                    future.set_result(json.loads(data))
                else:
                    future.set_result(data)
            else:
                future.set_exception(NetworkError.from_reply(reply))
        except Exception as e:
            future.set_exception(e)

    def _cleanup(self):
        self._requests = {
            reply: request for reply, request in self._requests.items() if not reply.isFinished()
        }