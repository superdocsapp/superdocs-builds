from fastapi import Request

from docrelay.services.machine import MachineOperations


def machine_operations(request: Request) -> MachineOperations:
    return request.app.state.machine_operations
