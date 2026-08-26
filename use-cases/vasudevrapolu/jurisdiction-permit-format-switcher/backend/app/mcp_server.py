from mcp.server.fastmcp import FastMCP
from app.schemas.permit import PermitRequest, ProjectRecord
from app.services.permit_service import PermitService

mcp=FastMCP("document-engine")
service=PermitService()

@mcp.tool()
async def generate_permit_packet(project: dict, jurisdiction_id: str, master_narrative: str = "") -> dict:
    """Generate a jurisdiction-shaped synthetic solar permit packet."""
    req=PermitRequest(project=ProjectRecord(**project), jurisdiction_id=jurisdiction_id, master_narrative=master_narrative)
    packet=await service.generate(req)
    return packet.model_dump()

if __name__ == "__main__":
    mcp.run()
