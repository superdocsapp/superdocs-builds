from app.services.superdocs import superdocs_client


class ExportService:
    
    async def export_document(
        self,
        session_id: str,
        export_format: str,
        document_id: str | None = None,
    ):
        return await superdocs_client.export_document(
            session_id=session_id,
            export_format=export_format,
            document_id=document_id,
        )


export_service = ExportService()

