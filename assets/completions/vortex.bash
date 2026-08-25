_vortex_completions() {
  local cur prev commands
  cur="${COMP_WORDS[COMP_CWORD]}"; prev="${COMP_WORDS[COMP_CWORD-1]}"
  commands="ask plan run doctor tools engagement history explain undo session config model knowledge completion report theme"
  if [[ "${COMP_CWORD}" -eq 1 ]]; then COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") ); return; fi
  case "${COMP_WORDS[1]}" in
    engagement) COMPREPLY=( $(compgen -W "list create show close" -- "${cur}") ) ;;
    tools) COMPREPLY=( $(compgen -W "list probe show" -- "${cur}") ) ;;
    completion) COMPREPLY=( $(compgen -W "bash zsh fish" -- "${cur}") ) ;;
    theme) COMPREPLY=( $(compgen -W "show preview export install uninstall" -- "${cur}") ) ;;
    *) COMPREPLY=() ;;
  esac
}
complete -F _vortex_completions vortex
