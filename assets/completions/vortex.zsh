#compdef vortex
_vortex() {
  _arguments '1:command:(ask plan run doctor tools adapters artifact backup db migrate shell engagement history explain undo session config model knowledge completion report theme host-tools mobile)' '*::arg:->args'
  case "$words[2]" in
    engagement) _values 'action' list create show close ;;
    tools) _values 'action' list probe show ;;
    host-tools) _values 'action' list rescan ;;
    mobile) _values 'action' apk ;;
    completion) _values 'shell' bash zsh fish ;;
    theme) _values 'action' show preview export install uninstall ;;
    shell) _values 'action' preview install uninstall bash zsh fish ;;
  esac
}
_vortex "$@"
