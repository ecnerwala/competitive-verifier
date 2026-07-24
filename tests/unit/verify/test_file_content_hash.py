import datetime
import pathlib

import pytest
from pytest_mock import MockerFixture

from competitive_verifier.models import (
    ProblemVerification,
    VerificationInput,
)
from competitive_verifier.verify.verifier import InputContainer


class HashInputContainer(InputContainer):
    def __init__(self, verifications: VerificationInput) -> None:
        super().__init__(
            verifications=verifications,
            verification_time=datetime.datetime.now(),
            prev_result=None,
            split_state=None,
            prev_result_mode="hash",
        )

    def get_file_timestamp(self, path: pathlib.Path) -> datetime.datetime:
        raise NotImplementedError


@pytest.fixture
def verifications(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> VerificationInput:
    monkeypatch.chdir(tmp_path)
    pathlib.Path("foo.py").write_bytes(b"print(1)")
    return VerificationInput.model_validate(
        {
            "files": {
                "foo.py": {
                    "verification": {
                        "type": "problem",
                        "problem": "https://judge.yosupo.jp/problem/aplusb",
                        "command": "true",
                    },
                },
            },
        }
    )


@pytest.mark.allow_mkdir
def test_file_content_hash_includes_testdata_hash(
    verifications: VerificationInput,
    mocker: MockerFixture,
):
    hashes: list[str] = []
    for testdata_hash in [None, "version1", "version2"]:
        mocker.patch.object(
            ProblemVerification,
            "testdata_hash",
            return_value=testdata_hash,
        )
        h = HashInputContainer(verifications).file_content_hash(pathlib.Path("foo.py"))
        assert h is not None
        hashes.append(h)
    assert len(set(hashes)) == len(hashes)


@pytest.mark.allow_mkdir
def test_file_content_hash_stable_for_same_testdata_hash(
    verifications: VerificationInput,
    mocker: MockerFixture,
):
    mocker.patch.object(
        ProblemVerification,
        "testdata_hash",
        return_value="version1",
    )
    path = pathlib.Path("foo.py")
    assert HashInputContainer(verifications).file_content_hash(
        path
    ) == HashInputContainer(verifications).file_content_hash(path)
