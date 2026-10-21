import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Combobox } from "../components/Combobox";

function OrgSelect() {
  const [value, setValue] = useState("a");
  return (
    <Combobox
      id="org"
      label="Organization"
      value={value}
      options={[
        { id: "a", label: "Northstar Systems" },
        { id: "b", label: "Meridian HealthTech" },
      ]}
      onChange={setValue}
      searchable={false}
    />
  );
}

describe("dropdown panel clamping", () => {
  it("keeps a portaled panel inside a 320px viewport with gutter", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 320 });
    Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: 568 });
    const user = userEvent.setup();
    render(<OrgSelect />);
    const trigger = screen.getByRole("combobox", { name: /organization/i });
    trigger.getBoundingClientRect = () =>
      ({
        x: 0,
        y: 80,
        top: 80,
        left: 0,
        right: 320,
        bottom: 124,
        width: 320,
        height: 44,
        toJSON() {},
      }) as DOMRect;
    await user.click(trigger);
    const panel = document.querySelector(".dropdown-panel");
    expect(panel).toBeInstanceOf(HTMLElement);
    const style = (panel as HTMLElement).style;
    expect(Number.parseFloat(style.left)).toBe(12);
    expect(Number.parseFloat(style.width)).toBe(296);
    expect(document.documentElement.scrollWidth).toBe(document.documentElement.clientWidth);
  });
});
