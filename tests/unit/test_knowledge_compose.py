from pathlib import Path

import yaml


def test_runtime_document_isolation_and_no_model_key():
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "compose.knowledge.yaml").read_text())
    services = config["services"]
    assert config["networks"]["document_parser"]["internal"] is True
    assert config["networks"]["document_vectors"]["internal"] is True
    for name in ("knowledge", "knowledge-ops", "document-parser", "qdrant"):
        service = services[name]
        assert not service.get("ports") and service["read_only"]
        assert "ALL" in service["cap_drop"]
        assert "openrouter_key" not in str(service.get("secrets"))
        assert "model_download" not in service["networks"]
        assert all(item.startswith("/tmp:") for item in service["tmpfs"])
    parser = services["document-parser"]
    assert not parser.get("secrets") and not parser.get("volumes")
    assert parser["networks"] == ["document_parser"]
    downloader = services["knowledge-model-download"]
    assert not downloader.get("secrets")
    assert downloader["volumes"] == ["embedding-models:/models"]
    assert downloader["networks"] == ["model_download"]
    assert services["knowledge"]["environment"]["HF_HUB_OFFLINE"] == "1"


def test_knowledge_bootstrap_has_minimal_required_privileges():
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "compose.knowledge.yaml").read_text())
    services = config["services"]

    init = services["knowledge-init"]

    # Bootstrap alone may run as root so it can prepare named volumes.
    assert str(init["user"]) == "0:0"
    assert init["read_only"] is True
    assert init["network_mode"] == "none"
    assert "ALL" in init["cap_drop"]

    # Required for creating/chowning private UID-10001 directories
    # after /models itself has been changed to mode 0700.
    assert set(init["cap_add"]) == {"CHOWN", "FOWNER", "DAC_OVERRIDE"}

    assert "document-data:/data/documents" in init["volumes"]
    assert "embedding-models:/models" in init["volumes"]
    assert "qdrant-data:/qdrant/storage" in init["volumes"]

    command = " ".join(init["command"])
    for path in (
        "/data/documents",
        "/models",
        "/models/huggingface",
        "/models/huggingface/hub",
        "/models/cache",
        "/qdrant/storage",
    ):
        assert path in command

    assert "os.chmod(p,0o700)" in command
    assert "os.chown(p,10001,10001)" in command


def test_model_downloader_uses_private_writable_cache_without_extra_privileges():
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "compose.knowledge.yaml").read_text())
    downloader = config["services"]["knowledge-model-download"]

    assert downloader["read_only"] is True
    assert "ALL" in downloader["cap_drop"]
    assert not downloader.get("cap_add")
    assert downloader["volumes"] == ["embedding-models:/models"]

    env = downloader["environment"]
    assert env["JARVIS_EMBEDDING_CACHE"] == "/models"
    assert env["HF_HOME"] == "/models/huggingface"
    assert env["HF_HUB_CACHE"] == "/models/huggingface/hub"
    assert env["XDG_CACHE_HOME"] == "/models/cache"
    assert env["HF_HUB_DISABLE_XET"] == "1"
    assert env["HF_HUB_DISABLE_TELEMETRY"] == "1"
