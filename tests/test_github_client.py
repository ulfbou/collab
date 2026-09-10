from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from collab.github import GitHubClient, GitHubError
from collab.process import CommandResult


class GitHubClientTests(unittest.TestCase):
    def result(self, argv, value):
        return CommandResult(tuple(argv), 0, json.dumps(value).encode(), b"", 1)

    def test_authentication_and_identical_reads_execute_once(self):
        calls=[]
        def run(argv, **kwargs):
            calls.append(tuple(argv))
            return self.result(argv, {} if argv[-2:] == ["auth", "status"] else [{"number": 1}])
        with patch("collab.github.run_command", side_effect=run):
            client=GitHubClient(command=("gh",))
            first=client.request_json(["issue", "list", "--json", "number"])
            first.value.append({"number": 99})
            second=client.request_json(["issue", "list", "--json", "number"])
        self.assertEqual([{"number": 1}], second.value)
        self.assertEqual(1, sum(call[-2:] == ("auth", "status") for call in calls))
        self.assertEqual(1, sum("issue" in call for call in calls))

    def test_concurrent_identical_reads_are_single_flight(self):
        lock=threading.Lock(); counts={"auth":0,"request":0}
        def run(argv, **kwargs):
            if argv[-2:] == ["auth", "status"]:
                with lock: counts["auth"] += 1
                return self.result(argv,{})
            with lock: counts["request"] += 1
            time.sleep(0.05)
            return self.result(argv,{"ok":True})
        client=GitHubClient(command=("gh",)); barrier=threading.Barrier(8); values=[]
        def worker():
            barrier.wait(); values.append(client.request_json(["repo","view","--json","name"]).value)
        with patch("collab.github.run_command", side_effect=run):
            threads=[threading.Thread(target=worker) for _ in range(8)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
        self.assertEqual([{"ok":True}]*8, values)
        self.assertEqual({"auth":1,"request":1}, counts)

    def test_failed_request_is_not_cached(self):
        attempts=0
        def run(argv, **kwargs):
            nonlocal attempts
            if argv[-2:] == ["auth", "status"]: return self.result(argv,{})
            attempts += 1
            if attempts == 1: raise GitHubError("temporary")
            return self.result(argv,{"ok":True})
        client=GitHubClient(command=("gh",))
        with patch("collab.github.run_command", side_effect=run):
            with self.assertRaises(GitHubError): client.request_json(["api","repos/o/r"])
            self.assertEqual({"ok":True}, client.request_json(["api","repos/o/r"]).value)
        self.assertEqual(2, attempts)

    def test_mutations_bypass_cache_and_read_api_rejects_cache_disable(self):
        calls=[]
        def run(argv, **kwargs):
            calls.append(tuple(argv)); return self.result(argv,{})
        client=GitHubClient(command=("gh",))
        with patch("collab.github.run_command", side_effect=run):
            with self.assertRaises(GitHubError): client.request_json(["issue","create"], cache=False)
            client.mutate_json(["issue","create","--title","one"])
            client.mutate_json(["issue","create","--title","one"])
        self.assertEqual(2, sum("create" in call for call in calls))

    def test_request_identity_and_rest_fields_are_deterministic(self):
        calls=[]
        def run(argv, **kwargs):
            calls.append(tuple(argv)); return self.result(argv,[])
        client=GitHubClient(command=("gh",))
        with patch("collab.github.run_command", side_effect=run):
            first=client.rest("repos/o/r/issues",fields={"state":"open","page":"1"})
            second=client.rest("repos/o/r/issues",fields={"page":"1","state":"open"})
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(1, sum("repos/o/r/issues" in call for call in calls))


if __name__ == "__main__": unittest.main()
