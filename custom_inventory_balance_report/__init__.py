from . import wizard

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(*args):
    """Create Inventory > Reporting > Inventory Balance Report menu safely.

    - Uses Python (not XML menuitem) so install never fails on a missing
      parent XML ID.
    - Compatible with both ``(env)`` and ``(cr, registry)`` signatures.
    - Idempotent: never creates a duplicate menu; repairs the action if
      an existing menu has a wrong/missing action.
    - If no parent candidate is found, NO menu is created (no top-level
      fallback) and a clear log message is written. Install still succeeds.
    """
    from odoo import api, SUPERUSER_ID

    # --- resolve env from either hook signature ---
    if len(args) == 1:
        env = args[0]
    elif len(args) == 2:
        env = api.Environment(args[0], SUPERUSER_ID, {})
    else:
        return

    Menu = env["ir.ui.menu"]

    # ------------------------------------------------------------------
    # ORM metadata verification (no Odoo source inspection)
    # ------------------------------------------------------------------
    action_field = Menu._fields.get("action")
    if action_field is None:
        _logger.warning(
            "custom_inventory_balance_report: ir.ui.menu has no 'action' "
            "field in this Odoo build; menu not created."
        )
        return
    _logger.info(
        "custom_inventory_balance_report: ir.ui.menu.action field "
        "type=%s comodel_name=%s",
        action_field.type,
        getattr(action_field, "comodel_name", None),
    )
    if action_field.type != "reference":
        _logger.warning(
            "custom_inventory_balance_report: ir.ui.menu.action has "
            "unexpected type %r (expected 'reference'); menu not created "
            "to avoid a Wrong value error.",
            action_field.type,
        )
        return

    # ------------------------------------------------------------------
    # 1. Find the existing Window Action named "Inventory Balance Report"
    # ------------------------------------------------------------------
    action = env.ref(
        "custom_inventory_balance_report.action_inventory_balance_report",
        raise_if_not_found=False,
    )
    if not action:
        # Fallback: search by model in case the XML ID is stale
        action = env["ir.actions.act_window"].search(
            [("name", "=", "Inventory Balance Report")], limit=1
        )
    if not action:
        _logger.warning(
            "custom_inventory_balance_report: window action "
            "'Inventory Balance Report' not found; menu not created."
        )
        return

    # ------------------------------------------------------------------
    # 4. Reference value must be the string "ir.actions.act_window,<id>"
    #    NEVER pass action.id (an int) to ir.ui.menu.action.
    # ------------------------------------------------------------------
    action_reference = f"ir.actions.act_window,{action.id}"

    # Defensive assertion: must be str, must contain a comma, must not be int
    assert isinstance(action_reference, str), (
        "action_reference must be str, got %s" % type(action_reference).__name__
    )
    assert "," in action_reference
    assert not isinstance(action_reference, int)

    # ------------------------------------------------------------------
    # 7/8. Try parent candidates safely (never stock.menu_stock_root)
    # ------------------------------------------------------------------
    parent = None
    for xmlid in ("stock.menu_stock_report", "stock.menu_warehouse_report"):
        rec = env.ref(xmlid, raise_if_not_found=False)
        if rec and rec.exists():
            parent = rec
            break

    # 10. No parent → no top-level fallback, just warn; install succeeds
    if not parent:
        _logger.warning(
            "custom_inventory_balance_report: neither "
            "'stock.menu_stock_report' nor 'stock.menu_warehouse_report' "
            "was found. The menu 'Inventory Balance Report' was NOT created "
            "(no top-level fallback). The report action itself was created "
            "successfully and can be used."
        )
        return

    parent_name = (
        parent.complete_name if hasattr(parent, "complete_name") else parent.name
    )

    # ------------------------------------------------------------------
    # 11. Idempotent: find existing menu under this parent
    # ------------------------------------------------------------------
    existing = Menu.search(
        [
            ("name", "=", "Inventory Balance Report"),
            ("parent_id", "=", parent.id),
        ],
        limit=1,
    )

    if existing:
        # If the action is wrong/missing, repair it with the correct
        # Reference string (never an integer).
        current = existing.action  # Reference field reads back as "model,id" or False
        if current != action_reference:
            existing.write({"action": action_reference})
            _logger.info(
                "custom_inventory_balance_report: menu 'Inventory Balance "
                "Report' already existed under '%s'; action repaired to "
                "'%s'.",
                parent_name,
                action_reference,
            )
        else:
            _logger.info(
                "custom_inventory_balance_report: menu 'Inventory Balance "
                "Report' already exists under '%s' with correct action "
                "'%s'.",
                parent_name,
                action_reference,
            )
        return

    # ------------------------------------------------------------------
    # 6. Create the menu with a Reference STRING, never action.id
    # ------------------------------------------------------------------
    Menu.create(
        {
            "name": "Inventory Balance Report",
            "action": action_reference,  # "ir.actions.act_window,<id>"
            "parent_id": parent.id,
            "sequence": 50,
        }
    )

    # ------------------------------------------------------------------
    # 12. Required log line
    # ------------------------------------------------------------------
    _logger.info(
        "custom_inventory_balance_report: menu 'Inventory Balance Report' "
        "created under '%s' with action reference '%s'.",
        parent_name,
        action_reference,
    )
