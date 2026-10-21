import { ExportDropdown, type ExportDropdownProps } from './ExportDropdown'

export type ExportButtonProps = ExportDropdownProps

export function ExportButton(props: ExportButtonProps) {
  return <ExportDropdown {...props} />
}


