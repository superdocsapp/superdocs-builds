import { Combobox, type ComboboxOption, type ComboboxProps } from "./Combobox";

export type SelectOption = ComboboxOption;

export function Select(props: Omit<ComboboxProps, "searchable">) {
  return <Combobox {...props} searchable={false} />;
}
