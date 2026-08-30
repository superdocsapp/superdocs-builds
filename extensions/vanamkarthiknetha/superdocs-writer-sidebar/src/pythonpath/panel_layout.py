# Geometry for the sidebar panel.
#
# panel.xdl is a bulletin board: every control sits at a fixed coordinate and
# nothing reflows on its own, so in a short office window the bottom of the
# stack - the status line - fell outside the visible panel entirely. This
# module owns the layout instead: given the panel's current pixel size it says
# where every control goes, shrinking the flexible boxes so the decision
# buttons and the status line always stay on screen.
#
# Pure arithmetic, no UNO - tests/layout_test.py drives it directly.
#
# Sizes are in appfont units (what panel.xdl is authored in); panel.py measures
# the pixels-per-unit from a control it already owns, so the layout follows the
# host's DPI and font scaling rather than assuming a factor.

PAD = 4           # panel margin
GAP = 4           # vertical gutter between blocks
BTN_GAP = 6       # horizontal gutter between Apply and Reject
SEND_UNITS = 14   # btnSend's authored height: the pixel-per-unit yardstick
DECIDE = "__decide"   # pseudo-block for the Apply/Reject row

# Tiers per block: (id, floor, minimum, preferred, grow-weight). Preferred is
# the panel.xdl geometry; minimum is still comfortable; floor is what a block
# collapses to when the panel is genuinely tiny (0 = hidden). Grow-weight
# shares out the slack in a tall panel.
FLOOR, MIN, PREF, GROW = 1, 2, 3, 4

# Space is taken back in this order - first down to each block's minimum, then
# down to its floor. The instruction box yields before the preview: once a
# proposal is on screen, reading it matters more than the box that asked for
# it. The decision buttons never shrink, and the status line keeps a line of
# text at every size - that is the whole point of this module.
SHRINK_ORDER = ("lblHint", "lblPreview", "txtInstruction", "lblStatus", "lblTitle")
COLLAPSE_ORDER = ("lblTitle", "lblHint", "txtInstruction", "lblPreview", "lblStatus")


def blocks(has_preview):
    """The control column, top to bottom, at every sizing tier."""
    # An empty preview takes no room at all - before a proposal arrives that
    # space belongs to the instruction box and the status line.
    preview = (0, 20, 64, 3) if has_preview else (0, 0, 0, 0)
    return (
        ("lblTitle",        0, 10, 10, 0),
        ("lblHint",         0,  0, 18, 0),
        ("chkWholeDoc",    10, 10, 10, 0),
        ("txtInstruction", 14, 22, 48, 2),
        ("btnSend",        14, 14, 14, 0),
        ("lblPreview",) + preview,
        (DECIDE,           14, 14, 14, 0),
        ("lblStatus",      10, 20, 40, 1),
    )


def _px(units, unit):
    return int(round(units * unit))


def _stacked(heights, unit):
    """Total height in px of a column of block heights, gutters included.
    A zero-height block is hidden and takes its gutter with it."""
    shown = [h for h in heights if h > 0]
    return sum(shown) + _px(GAP, unit) * max(0, len(shown) - 1) + 2 * _px(PAD, unit)


def stack_height(tier, unit, has_preview=False):
    """Height in px the whole column needs at one sizing tier."""
    return _stacked([_px(b[tier], unit) for b in blocks(has_preview)], unit)


def solve(width, height, unit, has_preview=False):
    """Place every control inside a width x height panel (pixels).

    Returns ((control_id, rect), ...) top to bottom, where rect is
    (x, y, width, height) or None when the control is hidden at this size.
    """
    pad, gap = _px(PAD, unit), _px(GAP, unit)
    column = blocks(has_preview)
    size = {b[0]: _px(b[PREF], unit) for b in column}
    tiers = {b[0]: b for b in column}

    def used():
        return _stacked([size[b[0]] for b in column], unit)

    # Too tall for the panel: give space back, minimum tier first, then floor.
    for tier, order in ((MIN, SHRINK_ORDER), (FLOOR, COLLAPSE_ORDER)):
        for bid in order:
            short = used() - height
            if short <= 0:
                break
            size[bid] = max(_px(tiers[bid][tier], unit), size[bid] - short)

    # Room to spare: hand it to the boxes that can use it.
    extra = height - used()
    weights = {b[0]: b[GROW] for b in column if size[b[0]] > 0 and b[GROW]}
    if extra > 0 and weights:
        total, given, ids = sum(weights.values()), 0, list(weights)
        for bid in ids[:-1]:
            share = extra * weights[bid] // total
            size[bid] += share
            given += share
        size[ids[-1]] += extra - given

    placed = []
    inner = max(1, width - 2 * pad)
    y = pad
    for block in column:
        bid, tall = block[0], size[block[0]]
        if bid == DECIDE:
            # Apply and Reject split the row and align with both margins.
            wide = max(1, (inner - _px(BTN_GAP, unit)) // 2)
            placed.append(("btnApprove", (pad, y, wide, tall) if tall else None))
            placed.append(("btnReject",
                           (pad + inner - wide, y, wide, tall) if tall else None))
        else:
            placed.append((bid, (pad, y, inner, tall) if tall else None))
        if tall > 0:
            y += tall + gap
    return tuple(placed)
