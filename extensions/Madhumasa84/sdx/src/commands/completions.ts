import { SdxError } from '../api/errors.js';
import { EXIT_CODES } from '../core/exit-codes.js';

const commands = 'edit new approve resume auth profiles sessions completions doctor';
const options = '--profile --session --json --output --export --timeout --verbose --no-color';

const BASH = `# sdx bash completion
_sdx_completion() {
  local cur prev
  COMPREPLY=()
  cur="${'${COMP_WORDS[COMP_CWORD]}'}"
  prev="${'${COMP_WORDS[COMP_CWORD-1]}'}"
  case "$prev" in
    completions) COMPREPLY=( $(compgen -W "bash zsh fish" -- "$cur") ); return ;;
    --export|--format) COMPREPLY=( $(compgen -W "docx pdf html md txt" -- "$cur") ); return ;;
  esac
  COMPREPLY=( $(compgen -W "${commands} auth login status profiles list show use sessions list show remove ${options} --approve --accept --reject --accept-all --overwrite --title --poll-interval --diff-limit" -- "$cur") )
}
complete -F _sdx_completion sdx
`;

const ZSH = `#compdef sdx
_sdx() {
  local -a commands
  commands=(edit new approve resume auth profiles sessions completions doctor)
  _arguments '*::arg:->args' '${options}' '--approve' '--accept=[accepted IDs]' '--reject=[rejected IDs]' '--accept-all' '--overwrite' '--title=[title]' '--poll-interval=[milliseconds]' '--diff-limit=[characters]'
  _values 'sdx commands' $commands
}
_sdx "$@"
`;

const FISH = `# sdx fish completion
complete -c sdx -f
complete -c sdx -n '__fish_use_subcommand' -a '${commands}'
complete -c sdx -l profile -r
complete -c sdx -l session -r
complete -c sdx -l json
complete -c sdx -l output -r
complete -c sdx -l export -r -a 'docx pdf html md txt'
complete -c sdx -l timeout -r
complete -c sdx -l verbose
complete -c sdx -l no-color
complete -c sdx -l approve
complete -c sdx -l accept -r
complete -c sdx -l reject -r
complete -c sdx -l accept-all
complete -c sdx -l overwrite
complete -c sdx -l title -r
complete -c sdx -l poll-interval -r
complete -c sdx -l diff-limit -r
`;

export function completionScript(shell: string): string {
  if (shell === 'bash') return BASH;
  if (shell === 'zsh') return ZSH;
  if (shell === 'fish') return FISH;
  throw new SdxError('Completion shell must be bash, zsh, or fish.', EXIT_CODES.invalidInput);
}
