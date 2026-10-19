"""The transport never returns a partial body and raises nothing but TransportError; the watchdog only shuts the socket down
(closing it from the timer thread races the reading thread on Linux). Loopback servers started and stopped by the test."""
from __future__ import annotations

import http.client
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dispatch_third_fixes import Server, trickle  # noqa: E402

from batuta_lib.dispatch import transport  # noqa: E402


def request_read(conn):
    """The whole request (its body is `{}`), so closing the socket afterwards is an orderly close, never a reset."""
    conn.settimeout(2)
    data = b""
    while not data.endswith(b"{}"):
        data += conn.recv(65536)


def finish(conn):
    """An orderly end of the answer: stop sending, then wait for the client to close, so no reset overtakes the data."""
    try:
        conn.shutdown(socket.SHUT_WR)
        while conn.recv(1024):
            pass
    except OSError:
        pass


def short_body(length, sent):
    def handler(conn, stopped):
        request_read(conn)
        conn.sendall(f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n\r\n".encode() + b"x" * sent)
        finish(conn)
    return handler


def send(handler, budget=5.0):
    server = Server(handler)
    try:
        return transport.UrllibTransport().send("POST", f"http://127.0.0.1:{server.port}/v1/x", {}, b"{}", budget)
    finally:
        server.stop()


class NoPartialBody(unittest.TestCase):
    def test_a_body_shorter_than_its_content_length_is_a_transport_error(self):
        with self.assertRaises(transport.TransportError) as cm:
            send(short_body(100, 10))
        self.assertTrue(cm.exception.sent)

    def test_a_complete_body_is_returned(self):
        resp = send(short_body(10, 10))
        self.assertEqual((resp.status, resp.body), (200, b"x" * 10))

    def test_a_body_without_content_length_ends_with_the_connection(self):
        def handler(conn, stopped):
            request_read(conn)
            conn.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nhello")
            finish(conn)
        self.assertEqual(send(handler).body, b"hello")


class WatchdogOnlyShutsTheSocketDown(unittest.TestCase):
    def test_the_connection_is_closed_on_the_calling_thread_only(self):
        closers = []
        original = http.client.HTTPConnection.close

        def spy(self):
            closers.append(threading.current_thread())
            return original(self)

        server = Server(trickle("body"))
        try:
            with mock.patch.object(http.client.HTTPConnection, "close", spy):
                with self.assertRaises(transport.TransportError) as cm:
                    transport.UrllibTransport().send("POST", f"http://127.0.0.1:{server.port}/v1/x", {}, b"{}", 1.0)
        finally:
            server.stop()
        self.assertIn("time budget", str(cm.exception))
        self.assertTrue(cm.exception.sent)
        self.assertTrue(closers)
        self.assertEqual({t for t in closers}, {threading.current_thread()}, "the watchdog thread closed the connection")

    def test_an_exception_after_the_watchdog_fired_becomes_the_budget_error(self):
        class Boom(Exception):
            pass

        original = http.client.HTTPResponse.read1

        def late(self, *args):
            threading.Event().wait(1.5)       # the watchdog (1.0 s) fires while this read is pending
            raise Boom("closed under the reader")

        server = Server(trickle("body"))
        try:
            with mock.patch.object(http.client.HTTPResponse, "read1", late):
                with self.assertRaises(transport.TransportError) as cm:
                    transport.UrllibTransport().send("POST", f"http://127.0.0.1:{server.port}/v1/x", {}, b"{}", 1.0)
        finally:
            server.stop()
        self.assertIn("time budget", str(cm.exception))
        self.assertTrue(cm.exception.sent)
        self.assertIsNotNone(original)

    def test_a_read_that_ends_empty_after_the_watchdog_fired_is_the_budget_error(self):
        def late_empty(self, *args):
            threading.Event().wait(1.5)
            return b""

        server = Server(trickle("body"))
        try:
            with mock.patch.object(http.client.HTTPResponse, "read1", late_empty):
                with self.assertRaises(transport.TransportError) as cm:
                    transport.UrllibTransport().send("POST", f"http://127.0.0.1:{server.port}/v1/x", {}, b"{}", 1.0)
        finally:
            server.stop()
        self.assertIn("time budget", str(cm.exception))
