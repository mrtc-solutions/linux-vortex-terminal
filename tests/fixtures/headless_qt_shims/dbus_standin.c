/* Minimal link-time stand-in for libdbus-1 in headless acceptance containers.
   Qt's VNC platform plugin links libQt5DBus (which links libdbus-1) even though the
   acceptance target never uses a session bus. This stand-in exists so Qt can load
   and it reports the honest state of the machine: no session bus is available.
   Only the error helpers have real semantics; every lookup fails like a real
   libdbus does when the daemon is absent. Never shipped, never part of the app. */
#include <string.h>

typedef struct {
    const char *name;
    const char *message;
    unsigned int dummy1, dummy2, dummy3, dummy4, dummy5;
} DbusError;

void dbus_error_init(DbusError *error) { if (error) memset(error, 0, sizeof(DbusError)); }
int dbus_error_is_set(const DbusError *error) { return error && error->name != NULL; }
void dbus_error_free(DbusError *error) { if (error) memset(error, 0, sizeof(DbusError)); }
int dbus_error_has_name(const DbusError *error, const char *name) { (void)name; return error ? 0 : 0; }
const char *dbus_error_name(const DbusError *error) { return error ? error->name : 0; }
const char *dbus_error_message(const DbusError *error) { return error ? error->message : 0; }
void dbus_set_error(DbusError *error, const char *name, const char *message, ...) {
    if (!error) return;
    error->name = name;
    error->message = message;
}
void dbus_set_error_const(DbusError *error, const char *name, const char *message) {
    if (!error) return;
    error->name = name;
    error->message = message;
}

long dbus_bus_add_match(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_bus_get_private(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_bus_get_unique_name(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_bus_register(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_bus_remove_match(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_add_filter(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_can_send_type(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_close(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_dispatch(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_get_is_authenticated(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_get_is_connected(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_open_private(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_ref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_send(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_send_with_reply(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_set_allow_anonymous(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_set_dispatch_status_function(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_set_exit_on_disconnect(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_set_timeout_functions(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_set_watch_functions(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_unref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_connection_unregister_object_path(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_free(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_free_string_array(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_get_local_machine_id(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_append_args(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_append_args_valist(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_copy(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_demarshal(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_args(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_args_valist(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_auto_start(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_destination(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_error_name(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_interface(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_member(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_no_reply(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_path(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_reply_serial(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_serial(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_signature(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_get_type(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_is_signal(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_append_basic(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_append_fixed_array(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_close_container(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_get_arg_type(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_get_basic(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_get_element_type(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_get_fixed_array(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_get_signature(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_init(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_init_append(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_next(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_open_container(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_iter_recurse(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_new(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_new_error(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_new_method_call(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_new_method_return(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_new_signal(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_ref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_set_auto_start(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_set_no_reply(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_set_reply_serial(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_message_unref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_malloc(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_malloc0(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_move_error(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_new(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_pending_call_block(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_pending_call_get_completed(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_pending_call_ref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_pending_call_set_notify(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_pending_call_steal_reply(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_pending_call_unref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_server_unref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_set_error_from_message(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_signature_validate(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_threads_init_default(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_unref(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_validate_bus_name(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_validate_interface(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_validate_member(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_validate_path(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_watch_handle(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_watch_get_data(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_watch_get_enabled(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_watch_get_flags(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_watch_get_unix_fd(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
long dbus_watch_set_data(long a1, long a2, long a3, long a4, long a5, long a6, long a7, long a8) {
    (void)a1; (void)a2; (void)a3; (void)a4; (void)a5; (void)a6; (void)a7; (void)a8;
    return 0;
}
