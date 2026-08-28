_vortex_completions() {
  local cur prev commands
  cur="${COMP_WORDS[COMP_CWORD]}"; prev="${COMP_WORDS[COMP_CWORD-1]}"
  commands="ask plan run doctor tools adapters artifact backup db migrate shell engagement history explain undo session config model knowledge completion report theme host-tools mobile"
  if [[ "${COMP_CWORD}" -eq 1 ]]; then COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") ); return; fi
  case "${COMP_WORDS[1]}" in
    engagement) COMPREPLY=( $(compgen -W "list create show close" -- "${cur}") ) ;;
    tools) COMPREPLY=( $(compgen -W "list probe show" -- "${cur}") ) ;;
    host-tools) COMPREPLY=( $(compgen -W "list rescan" -- "${cur}") ) ;;
    mobile) COMPREPLY=( $(compgen -W "apk" -- "${cur}") ) ;;
    completion) COMPREPLY=( $(compgen -W "bash zsh fish" -- "${cur}") ) ;;
    theme) COMPREPLY=( $(compgen -W "show preview export install uninstall" -- "${cur}") ) ;;
    shell) COMPREPLY=( $(compgen -W "preview install uninstall bash zsh fish" -- "${cur}") ) ;;
    *) COMPREPLY=() ;;
  esac
}
complete -F _vortex_completions vortex
