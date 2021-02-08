#!/usr/bin/env python3

"""
Syntax:
  mvn-testalot.py 10  <-- Runs "mvn test" 10 times, retaining all surefire-reports XML files
  mvn-testalot.py report target/testalot/  <-- Produces a Markdown report on stdout
"""

import os
import re
import sys
import enum
import shutil
import datetime
import subprocess

from typing import List, NamedTuple, Dict


# Example: <testcase name="aclExcudeSingleCommand" classname="redis.clients.jedis.tests.commands.AccessControlListCommandsTest" time="0"/>
TESTCASE = re.compile(r'  <testcase name="([^"]+)" classname="([^"]+)" time="([^"]+)"')

# Example: <error message="ERR unknown command `ZMSCORE`, with args beginning with: `foo`, `b`, ...
ERROR = re.compile(r"    <error ")

# Example: <failure message="expected:&lt;4&gt; but was:&lt;3&gt;" type=...
FAILURE = re.compile(r"    <failure ")


class ResultKind(enum.Enum):
    PASS = enum.auto()
    FAIL = enum.auto()
    ERROR = enum.auto()


class Result(NamedTuple):
    name: str
    kind: ResultKind
    duration: datetime.timedelta


def mvn_test_times(count: int) -> List[Result]:
    global_start = datetime.datetime.now()
    for i in range(count):
        if os.path.isdir("target/surefire-reports"):
            shutil.rmtree("target/surefire-reports")

        if not os.path.isfile("pom.xml"):
            sys.exit("Must be in the root of the source tree, pom.xml not found")

        start = datetime.datetime.now()
        result = subprocess.run(args=["mvn", "test"])
        end = datetime.datetime.now()
        duration = end - start
        print("")
        print(f"mvn-testalot: Exit code {result.returncode} after {duration}")

        runs_left = count - 1 - i
        if runs_left:
            runs_done = i + 1
            time_elapsed = datetime.datetime.now() - global_start
            time_per_run = time_elapsed / runs_done
            time_left = time_per_run * runs_left
            eta = datetime.datetime.now() + time_left
            print(
                f"mvn-testalot: {runs_left} runs left, expect finish at {eta.isoformat(timespec='seconds')}, {time_left} from now"
            )

        assert os.path.isdir("target/surefire-reports")  # Otherwise no tests were run

        os.makedirs("target/testalot", exist_ok=True)

        # Example: "20210208T093519"
        timestamp = (
            datetime.datetime.now()
            .isoformat(timespec="seconds")
            .replace(":", "")
            .replace("-", "")
        )

        shutil.move(
            "target/surefire-reports", f"target/testalot/surefire-reports-{timestamp}"
        )

    now = datetime.datetime.now()
    print(f"mvn-testalot: All done at {now.isoformat(timespec='seconds')}")

    return collect_results(["target/testalot"])


def parse_xml(path: str):
    results: List[Result] = []
    current_test = None
    result_kind = None
    duration = None
    for line in open(path, "r"):
        if match := TESTCASE.match(line):
            if current_test:
                assert result_kind
                assert duration is not None
                results.append(Result(current_test, result_kind, duration))
            testname = match.group(1)
            classname = match.group(2)
            duration = datetime.timedelta(seconds=float(match.group(3)))
            current_test = classname + "." + testname + "()"
            result_kind = ResultKind.PASS
            continue

        if ERROR.match(line):
            assert result_kind == ResultKind.PASS
            result_kind = ResultKind.ERROR
        elif FAILURE.match(line):
            assert result_kind == ResultKind.PASS
            result_kind = ResultKind.FAIL

        # Unknown line, just ignore it

    if current_test:
        assert result_kind
        assert duration is not None
        results.append(Result(current_test, result_kind, duration))

    return results


def collect_results(paths: List[str]) -> List[Result]:
    results = []
    for path in paths:
        if os.path.isfile(path):
            if path.endswith(".xml"):
                results += parse_xml(path)
                continue

        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                file_with_path = os.path.join(dirpath, filename)
                if not file_with_path.endswith(".xml"):
                    continue

                results += parse_xml(file_with_path)

    return results


def print_slow_tests_report(results: List[Result]) -> None:
    durations: Dict[str, datetime.timedelta] = {}

    # Figure out max duration for each test case
    for result in results:
        duration = durations.get(result.name, datetime.timedelta())
        if result.duration > duration:
            duration = result.duration
        durations[result.name] = duration

    print("")
    print("# Slow tests")
    print("")
    print("| Duration | Name |")
    print("|----------|------|")

    print_count = 0
    for testname, duration in sorted(
        durations.items(), key=lambda x: x[1], reverse=True
    ):
        if print_count > 7:
            break
        print_count += 1

        print(f"| {duration} | `{testname}` |")


def print_flaky_tests_report(results: List[Result]) -> None:
    counts: Dict[str, Dict[ResultKind, int]] = {}
    for result in results:
        counts_for_result = counts.get(result.name, {})
        count_for_kind = counts_for_result.get(result.kind, 0)
        counts_for_result[result.kind] = count_for_kind + 1
        counts[result.name] = counts_for_result

    print("")
    print("# Flaky tests")
    print("")
    print("| Pass | Fail | Error | Name |")
    print("|------|------|-------|------|")
    for name in sorted(counts.keys()):
        stats = counts[name]
        if len(stats) == 1:
            # Not flaky, only one kind of result
            continue

        assert len(stats) > 0
        pazz = stats.get(ResultKind.PASS, 0)
        fail = stats.get(ResultKind.FAIL, 0)
        error = stats.get(ResultKind.ERROR, 0)
        print(f"| {pazz:4d} | {fail:4d} | {error:5d} | `{name}` |")


def print_report(results: List[Result]) -> None:
    print_slow_tests_report(results)
    print_flaky_tests_report(results)


def main(args: List[str]) -> None:
    count = None
    try:
        count = int(int(args[1]))
    except:
        # Didn't work, never mind
        pass

    if count:
        results = mvn_test_times(count)
        print_report(results)
        sys.exit(0)

    assert args[1] == "report"

    # Collect test results for the given path(s)
    results = collect_results(args[2:])
    print_report(results)


if __name__ == "__main__":
    main(sys.argv)
