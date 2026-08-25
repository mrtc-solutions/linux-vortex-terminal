#compdef vortex
_vortex() {
  _arguments '1:command:(ask plan run doctor tools engagement history explain undo session config model knowledge completion report theme)' '*::arg:->args'
  case "$words[2]" in
    engagement) _values 'action' list create show close ;;
    tools) _values 'action' list probe show ;;
    completion) _values 'shell' bash zsh fish ;;
    theme) _values 'action' show preview export install uninstall ;;
  esac
}
_vortex "$@"
