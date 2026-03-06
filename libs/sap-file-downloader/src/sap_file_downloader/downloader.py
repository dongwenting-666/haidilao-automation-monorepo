"""SAP file download automation."""

from pathlib import Path


class SAPFileDownloader:
    """Handles downloading files from SAP."""

    def __init__(self, host: str, username: str, password: str, port: int = 443):
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    def download(self, transaction: str, output_path: Path) -> Path:
        """Download a file from SAP for a given transaction."""
        raise NotImplementedError("TODO: implement SAP download logic")
