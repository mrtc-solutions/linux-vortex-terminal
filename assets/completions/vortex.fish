complete -c vortex -f -n '__fish_use_subcommand' -a 'ask plan run doctor tools adapters artifact backup db migrate shell engagement history explain undo session config model knowledge completion report theme host-tools mobile'
complete -c vortex -f -n '__fish_seen_subcommand_from completion' -a 'bash zsh fish'
complete -c vortex -f -n '__fish_seen_subcommand_from engagement' -a 'list create show close'
complete -c vortex -f -n '__fish_seen_subcommand_from tools' -a 'list probe show'
complete -c vortex -f -n '__fish_seen_subcommand_from theme' -a 'show preview export install uninstall'

complete -c vortex -f -n '__fish_seen_subcommand_from shell' -a 'preview install uninstall bash zsh fish'
