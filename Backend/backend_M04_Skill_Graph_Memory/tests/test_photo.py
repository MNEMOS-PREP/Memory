"""The student's picture (2026-11-17).

Set in Settings; shown in the corner of every page, on the student's tile in a
mock interview when their camera is off, and on the resumes they tailor. What
is pinned: only a real JPEG or PNG is kept, only the student (or staff) can
read it, the profile says whether there is one, and it leaves with the export
and goes with the delete like the rest of this module's memory.
"""

from __future__ import annotations

import base64
import struct
import uuid
import zlib

from fastapi.testclient import TestClient


def _png(width: int = 128, height: int = 128) -> bytes:
    """A real, tiny PNG — built here so the suite needs no image library."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _put(client: TestClient, candidate_id, data: bytes, mime: str = "image/png"):
    return client.put(
        f"/v1/candidates/{candidate_id}/photo", content=data, headers={"Content-Type": mime}
    )


def test_a_picture_is_kept_read_back_and_named_on_the_profile(client, candidate_id):
    assert client.get(f"/v1/candidates/{candidate_id}/profile").json()["photo"] == ""
    assert client.get(f"/v1/candidates/{candidate_id}/photo").status_code == 404

    saved = _put(client, candidate_id, _png())
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["mime"] == "image/png" and body["width"] == 128 and body["height"] == 128

    read = client.get(f"/v1/candidates/{candidate_id}/photo")
    assert read.status_code == 200 and read.content == _png()
    assert read.headers["content-type"] == "image/png"
    assert client.get(f"/v1/candidates/{candidate_id}/profile").json()["photo"] == body["sha256"]
    # Unchanged since last asked: nothing is sent again.
    again = client.get(
        f"/v1/candidates/{candidate_id}/photo", headers={"If-None-Match": read.headers["etag"]}
    )
    assert again.status_code == 304


def test_only_a_real_picture_is_kept(client, candidate_id):
    fake = _put(client, candidate_id, b"<svg onload=alert(1)>", "image/png")
    assert fake.status_code == 415
    assert _put(client, candidate_id, b"").status_code == 422
    assert _put(client, candidate_id, _png(16, 16)).status_code == 422
    assert (
        _put(client, candidate_id, b"\xff\xd8\xff" + b"0" * 1_600_000, "image/jpeg").status_code
        == 413
    )


def test_removing_the_picture_falls_back_to_nothing(client, candidate_id):
    _put(client, candidate_id, _png())
    assert client.delete(f"/v1/candidates/{candidate_id}/photo").status_code == 204
    assert client.get(f"/v1/candidates/{candidate_id}/photo").status_code == 404
    assert client.get(f"/v1/candidates/{candidate_id}/profile").json()["photo"] == ""


def test_another_student_cannot_see_your_picture(client, candidate_id):
    from backend_M04_Skill_Graph_Memory.app import app

    _put(client, candidate_id, _png())
    stranger = TestClient(app, headers={"X-Role": "student", "X-Candidate-Id": str(uuid.uuid4())})
    assert stranger.get(f"/v1/candidates/{candidate_id}/photo").status_code == 403
    owner = TestClient(app, headers={"X-Role": "student", "X-Candidate-Id": str(candidate_id)})
    assert owner.get(f"/v1/candidates/{candidate_id}/photo").status_code == 200


def test_the_picture_leaves_with_the_export_and_goes_with_the_delete(client, candidate_id):
    _put(client, candidate_id, _png())
    export = client.get(f"/v1/candidates/{candidate_id}/export").json()
    assert base64.b64decode(export["profile_photo"][0]["data_base64"]) == _png()
    client.delete(f"/v1/candidates/{candidate_id}/memory")
    assert client.get(f"/v1/candidates/{candidate_id}/photo").status_code == 404
