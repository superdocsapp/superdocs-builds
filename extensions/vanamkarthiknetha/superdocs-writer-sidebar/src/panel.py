# SuperDocs Writer Sidebar - UNO component.
# v0.2: selection round-trip. Send selection + instruction -> SuperDocs proposes
# an edit -> preview in the panel -> Apply writes the approved text back into
# the exact selected range (styles of the range are preserved; whole-document
# mode is the v0.3 milestone).
import re
import threading
import traceback

import unohelper

from com.sun.star.awt import XActionListener, XCallback
from com.sun.star.container import NoSuchElementException
from com.sun.star.lang import XServiceInfo
from com.sun.star.ui import XSidebarPanel, XToolPanel, XUIElement, XUIElementFactory, LayoutSize
from com.sun.star.ui.UIElementType import TOOLPANEL

import superdocs_client

EXT_ID = "app.superdocs.writer.sidebar.vanamkarthiknetha"
RESOURCE_PREFIX = "private:resource/toolpanel/SuperDocsPanelFactory"


def _strip_html(markup):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup or "")).strip()


def _proposal_preview(edit):
    """Quote the ACTUAL proposed content (new_html), not the AI's explanation -
    the explanation can paraphrase and the user is approving the real change."""
    proposed = " ".join(_strip_html(c.get("new_html")) for c in edit["pending"]
                        if c.get("new_html"))
    if proposed:
        clipped = proposed[:300] + ("..." if len(proposed) > 300 else "")
        return f'Proposed text: "{clipped}"'
    return edit["summary"][:300]


def _ext_file_url(ctx, relative):
    pip = ctx.getValueByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
    return pip.getPackageLocation(EXT_ID) + "/" + relative


class _Action(unohelper.Base, XActionListener):
    def __init__(self, handler):
        self._handler = handler

    def actionPerformed(self, _event):
        self._handler()

    def disposing(self, _event):
        self._handler = None


class _Job(unohelper.Base, XCallback):
    """One main-thread job. Holds the callable itself - a Python function must
    never be passed as the UNO `aData` argument (not convertible to Any; the
    call throws and the failure is silent inside an action listener)."""

    def __init__(self, fn):
        self._fn = fn

    def notify(self, _data):
        try:
            self._fn()
        except Exception:
            traceback.print_exc()


class _MainThread:
    """Runs python callables on the office main thread via AsyncCallback."""

    def __init__(self, ctx):
        self._ctx = ctx

    def post(self, fn):
        try:
            cb = self._ctx.ServiceManager.createInstanceWithContext(
                "com.sun.star.awt.AsyncCallback", self._ctx)
            cb.addCallback(_Job(fn), None)
        except Exception:
            fn()  # degraded fallback: run inline rather than lose the update


class SuperDocsPanel(unohelper.Base, XUIElement, XToolPanel, XSidebarPanel):
    def __init__(self, ctx, frame, parent_window, resource_url):
        self.ctx = ctx
        self.Frame = frame
        self.ResourceURL = resource_url
        self.Type = TOOLPANEL
        self._parent = parent_window
        self._window = None
        self._main = _MainThread(ctx)
        self._edit = None          # dict from superdocs_client.request_edit
        self._target_range = None  # XTextRange the edit applies to
        self._busy = False

    # ---- XUIElement ----
    def getRealInterface(self):
        if self._window is None:
            provider = self.ctx.ServiceManager.createInstanceWithContext(
                "com.sun.star.awt.ContainerWindowProvider", self.ctx)
            self._window = provider.createContainerWindow(
                _ext_file_url(self.ctx, "panel.xdl"), "", self._parent, None)
            self._window.getControl("btnSend").addActionListener(_Action(self.on_send))
            self._window.getControl("btnApprove").addActionListener(_Action(self.on_apply))
            self._window.getControl("btnReject").addActionListener(_Action(self.on_reject))
            self._window.setVisible(True)
        return self

    # ---- XToolPanel ----
    @property
    def Window(self):
        return self._window

    def createAccessible(self, _parent):
        return self._window.getAccessibleContext() if self._window else None

    # ---- XSidebarPanel ----
    def getHeightForWidth(self, _width):
        return LayoutSize(360, -1, 360)

    def getMinimalWidth(self):
        return 160

    # ---- ui helpers (safe from any thread via _MainThread.post) ----
    def _ui(self, status=None, preview=None, decisions_enabled=None, send_enabled=None):
        def apply_ui():
            if status is not None:
                self._window.getControl("lblStatus").getModel().Label = status
            if preview is not None:
                self._window.getControl("lblPreview").getModel().Label = preview
            if decisions_enabled is not None:
                self._window.getControl("btnApprove").getModel().Enabled = decisions_enabled
                self._window.getControl("btnReject").getModel().Enabled = decisions_enabled
            if send_enabled is not None:
                self._window.getControl("btnSend").getModel().Enabled = send_enabled
        self._main.post(apply_ui)

    def _progress(self, message):
        self._ui(status=message)

    def _fail(self, exc):
        self._busy = False
        self._ui(status=f"Error: {exc}", decisions_enabled=False, send_enabled=True)
        traceback.print_exc()

    # ---- actions ----
    def on_send(self):
        try:
            self._on_send()
        except Exception as exc:
            self._fail(exc)

    def _on_send(self):
        if self._busy:
            return
        instruction = self._window.getControl("txtInstruction").getText().strip()
        if not instruction:
            self._ui(status="Type an instruction first.")
            return
        controller = self.Frame.getController()
        selection = controller.getSelection()
        if (selection is None
                or not selection.supportsService("com.sun.star.text.TextRanges")
                or selection.getCount() == 0
                or not selection.getByIndex(0).getString().strip()):
            self._ui(status="Select the passage to edit first "
                            "(whole-document mode arrives in v0.3).")
            return
        self._target_range = selection.getByIndex(0)
        passage = self._target_range.getString()
        self._busy = True
        self._ui(status="Contacting SuperDocs...", preview="",
                 decisions_enabled=False, send_enabled=False)

        def work():
            try:
                edit = superdocs_client.request_edit(passage, instruction, self._progress)
                self._edit = edit
                if edit["state"] == "completed":
                    # nothing needed approval (e.g. no-op); report honestly
                    self._busy = False
                    self._ui(status="SuperDocs made no reviewable proposal "
                                    "(request may already be satisfied). Nothing changed.",
                             send_enabled=True)
                    return
                self._busy = False
                self._ui(status="Proposal ready - review and Apply or Reject.",
                         preview=_proposal_preview(edit),
                         decisions_enabled=True, send_enabled=False)
            except Exception as exc:
                self._fail(exc)

        threading.Thread(target=work, daemon=True).start()

    def on_apply(self):
        try:
            self._on_apply()
        except Exception as exc:
            self._fail(exc)

    def _on_apply(self):
        if self._busy or not self._edit:
            return
        self._busy = True
        self._ui(status="Applying...", decisions_enabled=False)

        def work():
            try:
                final_text = superdocs_client.finalize(self._edit, True, self._progress)

                def write_back():
                    # setString keeps the range's paragraph/character styles;
                    # only the selected range is touched.
                    self._target_range.setString(final_text)
                    self._edit = None
                    self._target_range = None
                    self._busy = False
                self._main.post(write_back)
                self._ui(status="Applied. Only the selected range was modified (1 operation).",
                         preview="", send_enabled=True)
            except Exception as exc:
                self._fail(exc)

        threading.Thread(target=work, daemon=True).start()

    def on_reject(self):
        try:
            self._on_reject()
        except Exception as exc:
            self._fail(exc)

    def _on_reject(self):
        if self._busy or not self._edit:
            return
        self._busy = True
        self._ui(status="Rejecting...", decisions_enabled=False)

        def work():
            try:
                superdocs_client.finalize(self._edit, False, self._progress)
                self._edit = None
                self._target_range = None
                self._busy = False
                self._ui(status="Rejected. Document untouched, nothing billed.",
                         preview="", send_enabled=True)
            except Exception as exc:
                self._fail(exc)

        threading.Thread(target=work, daemon=True).start()


class PanelFactory(unohelper.Base, XUIElementFactory, XServiceInfo):
    IMPL_NAME = "app.superdocs.writer.PanelFactory"
    SERVICE_NAMES = (IMPL_NAME,)

    def __init__(self, ctx):
        self.ctx = ctx

    def createUIElement(self, resource_url, arguments):
        if not resource_url.startswith(RESOURCE_PREFIX):
            raise NoSuchElementException(resource_url, self)
        frame = parent = None
        for arg in arguments:
            if arg.Name == "Frame":
                frame = arg.Value
            elif arg.Name == "ParentWindow":
                parent = arg.Value
        return SuperDocsPanel(self.ctx, frame, parent, resource_url)

    def getImplementationName(self):
        return self.IMPL_NAME

    def supportsService(self, name):
        return name in self.SERVICE_NAMES

    def getSupportedServiceNames(self):
        return self.SERVICE_NAMES


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(
    PanelFactory, PanelFactory.IMPL_NAME, PanelFactory.SERVICE_NAMES)
