import { NavLink } from "react-router-dom";
import type { NavIconName } from "../nav";
import { NavIcon } from "./icons";
import { Tooltip } from "./Tooltip";

export function SidebarNavItem({
  to,
  label,
  icon,
  collapsed = false,
  onNavigate,
}: {
  to: string;
  label: string;
  icon: NavIconName;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Tooltip text={label} enabled={collapsed}>
      <NavLink
        to={to}
        end={to === "/"}
        className="nav-item"
        onClick={onNavigate}
        aria-label={label}
      >
        <NavIcon name={icon} />
        <span className="nav-label">{label}</span>
      </NavLink>
    </Tooltip>
  );
}
