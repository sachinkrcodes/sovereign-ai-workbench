from tests.helpers import make_docx, make_pdf

URL = "/api/v1/documents"


def upload(client, name, data, content_type="application/octet-stream"):
    return client.post(URL, files={"file": (name, data, content_type)})


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["database"] == "up"


def test_request_id_header_is_returned(client):
    assert client.get("/health").headers["x-request-id"]


def test_upload_txt_creates_document_and_chunks(client, storage):
    response = upload(client, "notes.txt", b"Pump P-101 must be isolated before maintenance.")
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "notes.txt" and body["chunk_count"] == 1

    chunks = client.get(f"{URL}/{body['id']}/chunks").json()
    assert chunks["total"] == 1
    assert "isolated" in chunks["items"][0]["text"]
    assert storage.read(f"{body['id']}.txt").startswith(b"Pump")


def test_upload_pdf_keeps_page_numbers(client):
    response = upload(client, "manual.pdf", make_pdf(["Page one text", "Page two text"]))
    assert response.status_code == 201
    body = response.json()
    assert body["page_count"] == 2
    pages = [c["page_number"] for c in client.get(f"{URL}/{body['id']}/chunks").json()["items"]]
    assert pages == [1, 2]


def test_upload_docx(client):
    data = make_docx(["Shutdown checklist"], [["Step", "Owner"], ["1", "Ops"]])
    response = upload(client, "checklist.docx", data)
    assert response.status_code == 201
    assert response.json()["file_type"] == "docx"


def test_duplicate_file_returns_409_with_existing_id(client):
    first = upload(client, "a.txt", b"same content").json()
    second = upload(client, "b.txt", b"same content")
    assert second.status_code == 409
    assert second.json()["detail"]["document_id"] == first["id"]


def test_unsupported_extension_returns_415(client):
    assert upload(client, "virus.exe", b"MZ...").status_code == 415
    assert upload(client, "noextension", b"hello").status_code == 415


def test_renamed_file_returns_415(client):
    assert upload(client, "fake.pdf", b"this is plain text").status_code == 415


def test_too_large_returns_413(client):
    assert upload(client, "big.txt", b"a" * (1024 * 1024 + 10)).status_code == 413


def test_empty_file_returns_400(client):
    assert upload(client, "empty.txt", b"").status_code == 400


def test_pdf_without_text_returns_422(client):
    response = upload(client, "scan.pdf", make_pdf([""]))
    assert response.status_code == 422 and "OCR" in response.json()["detail"]


def test_filename_path_is_stripped(client):
    body = upload(client, "..\\..\\secret\\report.txt", b"quarterly numbers").json()
    assert body["filename"] == "report.txt"


def test_list_search_and_pagination(client):
    for name, text in [("alpha.txt", b"aaa"), ("beta.txt", b"bbb"), ("gamma.txt", b"ccc")]:
        upload(client, name, text)
    everything = client.get(URL).json()
    assert everything["total"] == 3
    assert client.get(URL, params={"q": "bet"}).json()["total"] == 1
    assert client.get(URL, params={"q": "%"}).json()["total"] == 0  # wildcards are escaped
    page = client.get(URL, params={"limit": 2, "offset": 2}).json()
    assert len(page["items"]) == 1 and page["total"] == 3


def test_get_unknown_document_returns_404(client):
    assert client.get(f"{URL}/doesnotexist").status_code == 404
    assert client.get(f"{URL}/doesnotexist/chunks").status_code == 404


def test_delete_removes_document_chunks_and_file(client, storage):
    body = upload(client, "temp.txt", b"delete me").json()
    key = f"{body['id']}.txt"
    assert storage.read(key)
    assert client.delete(f"{URL}/{body['id']}").status_code == 204
    assert client.get(f"{URL}/{body['id']}").status_code == 404
    assert not (storage.root / key).exists()
    assert client.delete(f"{URL}/{body['id']}").status_code == 404
