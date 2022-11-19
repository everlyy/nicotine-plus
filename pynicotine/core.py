# COPYRIGHT (C) 2020-2022 Nicotine+ Contributors
# COPYRIGHT (C) 2020-2022 Mathias <mail@mathias.is>
# COPYRIGHT (C) 2016-2017 Michael Labouebe <gfarmerfr@free.fr>
# COPYRIGHT (C) 2016 Mutnick <muhing@yahoo.com>
# COPYRIGHT (C) 2013 eLvErDe <gandalf@le-vert.net>
# COPYRIGHT (C) 2008-2012 quinox <quinox@users.sf.net>
# COPYRIGHT (C) 2009 hedonist <ak@sensi.org>
# COPYRIGHT (C) 2006-2009 daelstorm <daelstorm@gmail.com>
# COPYRIGHT (C) 2003-2004 Hyriand <hyriand@thegraveyard.org>
# COPYRIGHT (C) 2001-2003 Alexander Kanavin
#
# GNU GENERAL PUBLIC LICENSE
#    Version 3, 29 June 2007
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
This is the actual client code. Actual GUI classes are in the separate modules
"""

import os
import signal
import sys

from collections import deque
from threading import Thread

from pynicotine import slskmessages
from pynicotine.config import config
from pynicotine.logfacility import log


class Core:
    """ Core contains handlers for various messages from (mainly) the networking thread.
    This class links the networking thread and user interface. """

    def __init__(self):

        self.ui_callback = None
        self.network_filter = None
        self.statistics = None
        self.shares = None
        self.search = None
        self.transfers = None
        self.interests = None
        self.userbrowse = None
        self.userinfo = None
        self.userlist = None
        self.privatechat = None
        self.chatrooms = None
        self.pluginhandler = None
        self.now_playing = None
        self.protothread = None
        self.geoip = None
        self.notifications = None
        self.update_checker = None

        # Handle Ctrl+C and "kill" exit gracefully
        for signal_type in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signal_type, self.quit)

        self.bindip = None
        self.port = None

        self.shutdown = False
        self.user_status = slskmessages.UserStatus.OFFLINE
        self.login_username = None  # Only present while logged in
        self.user_ip_address = None
        self.privileges_left = None
        self.ban_message = "You are banned from downloading my shared files. Ban message: \"%s\""

        self.queue = deque()
        self.message_callbacks = {}
        self.user_addresses = {}
        self.user_statuses = {}
        self.watched_users = set()
        self.ip_requested = set()

    def init_components(self):

        from pynicotine.chatrooms import ChatRooms
        from pynicotine.geoip import GeoIP
        from pynicotine.interests import Interests
        from pynicotine.networkfilter import NetworkFilter
        from pynicotine.notifications import Notifications
        from pynicotine.nowplaying import NowPlaying
        from pynicotine.pluginsystem import PluginHandler
        from pynicotine.privatechat import PrivateChat
        from pynicotine.search import Search
        from pynicotine.shares import Shares
        from pynicotine.slskproto import SoulseekNetworkThread
        from pynicotine.statistics import Statistics
        from pynicotine.transfers import Transfers
        from pynicotine.updatechecker import UpdateChecker
        from pynicotine.userbrowse import UserBrowse
        from pynicotine.userinfo import UserInfo
        from pynicotine.userlist import UserList

        self.queue.clear()
        self.protothread = SoulseekNetworkThread(
            callback=self.thread_callback, queue=self.queue, user_addresses=self.user_addresses,
            bindip=self.bindip, port=self.port,
            interface=config.sections["server"]["interface"],
            port_range=config.sections["server"]["portrange"]
        )

        self.geoip = GeoIP()
        self.notifications = Notifications()
        self.network_filter = NetworkFilter()
        self.now_playing = NowPlaying()
        self.statistics = Statistics()
        self.update_checker = UpdateChecker()

        self.shares = Shares()
        self.search = Search()
        self.transfers = Transfers()
        self.interests = Interests()
        self.userbrowse = UserBrowse()
        self.userinfo = UserInfo()
        self.userlist = UserList()
        self.privatechat = PrivateChat()
        self.chatrooms = ChatRooms()
        self.pluginhandler = PluginHandler()

    def process_cli_input(self):

        while not self.shutdown:
            try:
                user_input = input()

            except EOFError:
                return

            if not user_input:
                continue

            command, *args = user_input.split(maxsplit=1)

            if command.startswith("/"):
                command = command[1:]

            if args:
                (args,) = args

            self.thread_callback([slskmessages.CLICommand(command, args)])

    """ Actions """

    def start(self, ui_callback, thread_callback):

        self.ui_callback = ui_callback
        self.thread_callback = thread_callback
        script_dir = os.path.dirname(__file__)

        log.add(_("Loading %(program)s %(version)s"), {"program": "Python", "version": config.python_version})
        log.add_debug("Using %(program)s executable: %(exe)s", {"program": "Python", "exe": str(sys.executable)})
        log.add_debug("Using %(program)s executable: %(exe)s", {"program": config.application_name, "exe": script_dir})
        log.add(_("Loading %(program)s %(version)s"), {"program": config.application_name, "version": config.version})

        self.init_components()

        self.protothread.start()
        self.shares.init_shares()
        self.transfers.init_transfers()
        self.statistics.load_statistics()
        self.privatechat.load_users()
        self.userlist.load_users()
        self.pluginhandler.load_enabled()

        Thread(target=self.process_cli_input, name="CLIInputProcessor", daemon=True).start()

        # Callback handlers for messages
        self.message_callbacks = {
            slskmessages.ServerDisconnect: self.server_disconnect,
            slskmessages.Login: self.login,
            slskmessages.ChangePassword: self.change_password,
            slskmessages.MessageUser: self.privatechat.message_user,
            slskmessages.PMessageUser: self.privatechat.p_message_user,
            slskmessages.ExactFileSearch: self.dummy_message,
            slskmessages.RoomAdded: self.dummy_message,
            slskmessages.RoomRemoved: self.dummy_message,
            slskmessages.UserJoinedRoom: self.chatrooms.user_joined_room,
            slskmessages.SayChatroom: self.chatrooms.say_chat_room,
            slskmessages.JoinRoom: self.chatrooms.join_room,
            slskmessages.UserLeftRoom: self.chatrooms.user_left_room,
            slskmessages.CantCreateRoom: self.dummy_message,
            slskmessages.QueuedDownloads: self.dummy_message,
            slskmessages.GetPeerAddress: self.get_peer_address,
            slskmessages.UserInfoReply: self.userinfo.user_info_reply,
            slskmessages.UserInfoRequest: self.userinfo.user_info_request,
            slskmessages.PierceFireWall: self.dummy_message,
            slskmessages.ConnectToPeer: self.connect_to_peer,
            slskmessages.CantConnectToPeer: self.dummy_message,
            slskmessages.PeerMessageProgress: self.peer_message_progress,
            slskmessages.SharedFileList: self.userbrowse.shared_file_list,
            slskmessages.GetSharedFileList: self.shares.get_shared_file_list,
            slskmessages.FileSearchRequest: self.dummy_message,
            slskmessages.FileSearchResult: self.search.file_search_result,
            slskmessages.GetUserStatus: self.get_user_status,
            slskmessages.GetUserStats: self.get_user_stats,
            slskmessages.Relogged: self.dummy_message,
            slskmessages.PeerInit: self.dummy_message,
            slskmessages.DownloadFile: self.transfers.file_download,
            slskmessages.UploadFile: self.transfers.file_upload,
            slskmessages.FileDownloadInit: self.transfers.file_download_init,
            slskmessages.FileUploadInit: self.transfers.file_upload_init,
            slskmessages.FileOffset: self.dummy_message,
            slskmessages.TransferRequest: self.transfers.transfer_request,
            slskmessages.TransferResponse: self.transfers.transfer_response,
            slskmessages.QueueUpload: self.transfers.queue_upload,
            slskmessages.UploadDenied: self.transfers.upload_denied,
            slskmessages.UploadFailed: self.transfers.upload_failed,
            slskmessages.PlaceInQueue: self.transfers.place_in_queue,
            slskmessages.DownloadFileError: self.transfers.download_file_error,
            slskmessages.UploadFileError: self.transfers.upload_file_error,
            slskmessages.DownloadConnectionClosed: self.transfers.download_connection_closed,
            slskmessages.UploadConnectionClosed: self.transfers.upload_connection_closed,
            slskmessages.PeerConnectionClosed: self.peer_connection_closed,
            slskmessages.FolderContentsResponse: self.transfers.folder_contents_response,
            slskmessages.FolderContentsRequest: self.shares.folder_contents_request,
            slskmessages.RoomList: self.chatrooms.room_list,
            slskmessages.LeaveRoom: self.chatrooms.leave_room,
            slskmessages.GlobalUserList: self.dummy_message,
            slskmessages.AddUser: self.add_user,
            slskmessages.PrivilegedUsers: self.privileged_users,
            slskmessages.AddToPrivileged: self.add_to_privileged,
            slskmessages.CheckPrivileges: self.check_privileges,
            slskmessages.ServerPing: self.dummy_message,
            slskmessages.ParentMinSpeed: self.dummy_message,
            slskmessages.ParentSpeedRatio: self.dummy_message,
            slskmessages.ParentInactivityTimeout: self.dummy_message,
            slskmessages.SearchInactivityTimeout: self.dummy_message,
            slskmessages.MinParentsInCache: self.dummy_message,
            slskmessages.WishlistInterval: self.search.set_wishlist_interval,
            slskmessages.DistribAliveInterval: self.dummy_message,
            slskmessages.DistribChildDepth: self.dummy_message,
            slskmessages.DistribBranchLevel: self.dummy_message,
            slskmessages.DistribBranchRoot: self.dummy_message,
            slskmessages.AdminMessage: self.admin_message,
            slskmessages.TunneledMessage: self.dummy_message,
            slskmessages.PlaceholdUpload: self.dummy_message,
            slskmessages.PlaceInQueueRequest: self.transfers.place_in_queue_request,
            slskmessages.UploadQueueNotification: self.dummy_message,
            slskmessages.FileSearch: self.search.search_request,
            slskmessages.RoomSearch: self.search.search_request,
            slskmessages.UserSearch: self.search.search_request,
            slskmessages.RelatedSearch: self.dummy_message,
            slskmessages.PossibleParents: self.dummy_message,
            slskmessages.DistribAlive: self.dummy_message,
            slskmessages.DistribSearch: self.search.distrib_search,
            slskmessages.ResetDistributed: self.dummy_message,
            slskmessages.ServerTimeout: self.server_timeout,
            slskmessages.SetConnectionStats: self.set_connection_stats,
            slskmessages.GlobalRecommendations: self.interests.global_recommendations,
            slskmessages.Recommendations: self.interests.recommendations,
            slskmessages.ItemRecommendations: self.interests.item_recommendations,
            slskmessages.SimilarUsers: self.interests.similar_users,
            slskmessages.ItemSimilarUsers: self.interests.item_similar_users,
            slskmessages.UserInterests: self.userinfo.user_interests,
            slskmessages.RoomTickerState: self.chatrooms.ticker_set,
            slskmessages.RoomTickerAdd: self.chatrooms.ticker_add,
            slskmessages.RoomTickerRemove: self.chatrooms.ticker_remove,
            slskmessages.UserPrivileged: self.dummy_message,
            slskmessages.AckNotifyPrivileges: self.dummy_message,
            slskmessages.NotifyPrivileges: self.dummy_message,
            slskmessages.PrivateRoomUsers: self.chatrooms.private_room_users,
            slskmessages.PrivateRoomOwned: self.chatrooms.private_room_owned,
            slskmessages.PrivateRoomAddUser: self.chatrooms.private_room_add_user,
            slskmessages.PrivateRoomRemoveUser: self.chatrooms.private_room_remove_user,
            slskmessages.PrivateRoomAdded: self.chatrooms.private_room_added,
            slskmessages.PrivateRoomRemoved: self.chatrooms.private_room_removed,
            slskmessages.PrivateRoomDisown: self.chatrooms.private_room_disown,
            slskmessages.PrivateRoomToggle: self.chatrooms.private_room_toggle,
            slskmessages.PrivateRoomSomething: self.dummy_message,
            slskmessages.PrivateRoomOperatorAdded: self.chatrooms.private_room_operator_added,
            slskmessages.PrivateRoomOperatorRemoved: self.chatrooms.private_room_operator_removed,
            slskmessages.PrivateRoomAddOperator: self.chatrooms.private_room_add_operator,
            slskmessages.PrivateRoomRemoveOperator: self.chatrooms.private_room_remove_operator,
            slskmessages.PublicRoomMessage: self.chatrooms.public_room_message,
            slskmessages.ShowConnectionErrorMessage: self.show_connection_error_message,
            slskmessages.CLICommand: self.cli_command,
            slskmessages.SchedulerCallback: self.scheduler_callback,
            slskmessages.UnknownPeerMessage: self.dummy_message
        }

    def confirm_quit(self, remember=False):

        if self.ui_callback and config.sections["ui"]["exitdialog"] != 0:  # 0: 'Quit program'
            self.ui_callback.confirm_quit(remember)
            return

        self.quit()

    def quit(self, signal_type=None, _frame=None):

        log.add(_("Quitting %(program)s %(version)s, %(status)s…"), {
            "program": config.application_name,
            "version": config.version,
            "status": _("terminating") if signal_type == signal.SIGTERM else _("application closing")
        })

        # Indicate that a shutdown has started, to prevent UI callbacks from networking thread
        self.shutdown = True

        if self.pluginhandler:
            self.pluginhandler.quit()

        # Shut down networking thread
        if self.protothread:
            self.protothread.abort()
            self.server_disconnect()

        # Save download/upload list to file
        if self.transfers:
            self.transfers.quit()

        # Closing up all shelves db
        if self.shares:
            self.shares.quit()

        if self.ui_callback:
            self.ui_callback.quit()

        log.add(_("Quit %(program)s %(version)s, %(status)s!"), {
            "program": config.application_name,
            "version": config.version,
            "status": _("terminated") if signal_type == signal.SIGTERM else _("done")
        })
        log.close_log_files()

    def connect(self):

        if not self.protothread.server_disconnected:
            return True

        if config.need_config():
            log.add(_("You need to specify a username and password before connecting…"))
            self.ui_callback.setup()
            return False

        valid_network_interface = self.protothread.validate_network_interface()

        if not valid_network_interface:
            message = _(
                "The network interface you specified, '%s', does not exist. Change or remove the specified "
                "network interface and restart Nicotine+."
            )
            log.add(message, self.protothread.interface, title=_("Unknown Network Interface"))
            return False

        valid_listen_port = self.protothread.validate_listen_port()

        if not valid_listen_port:
            message = _(
                "The range you specified for client connection ports was "
                "{}-{}, but none of these were usable. Increase and/or ".format(self.protothread.portrange[0],
                                                                                self.protothread.portrange[1])
                + "move the range and restart Nicotine+."
            )
            if self.protothread.portrange[0] < 1024:
                message += "\n\n" + _(
                    "Note that part of your range lies below 1024, this is usually not allowed on"
                    " most operating systems with the exception of Windows."
                )
            log.add(message, title=_("Port Unavailable"))
            return False

        # Clear any potential messages queued up while offline
        self.queue.clear()

        addr = config.sections["server"]["server"]
        login = config.sections["server"]["login"]
        password = config.sections["server"]["passw"]

        self.protothread.server_disconnected = False
        self.queue.append(slskmessages.ServerConnect(addr, login=(login, password)))
        return True

    def disconnect(self):
        self.queue.append(slskmessages.ServerDisconnect())

    def send_message_to_peer(self, user, message):
        """ Sends message to a peer. Used when we know the username of a peer,
        but don't have/know an active connection. """

        self.queue.append(slskmessages.SendNetworkMessage(user, message))

    def set_away_mode(self, is_away, save_state=False):

        if save_state:
            config.sections["server"]["away"] = is_away

        self.user_status = slskmessages.UserStatus.AWAY if is_away else slskmessages.UserStatus.ONLINE
        self.request_set_status(is_away and 1 or 2)

        # Reset away message users
        self.privatechat.set_away_mode(is_away)
        self.ui_callback.set_away_mode(is_away)

    def request_change_password(self, password):
        self.queue.append(slskmessages.ChangePassword(password))

    def request_check_privileges(self):
        self.queue.append(slskmessages.CheckPrivileges())

    def request_give_privileges(self, user, days):
        self.queue.append(slskmessages.GivePrivileges(user, days))

    def request_ip_address(self, username):
        self.ip_requested.add(username)
        self.queue.append(slskmessages.GetPeerAddress(username))

    def request_set_status(self, status):
        self.queue.append(slskmessages.SetStatus(status))

    def get_user_country(self, user):
        """ Retrieve a user's country code if previously cached, otherwise request
        user's IP address to determine country """

        if self.user_status == slskmessages.UserStatus.OFFLINE:
            return None

        user_address = self.user_addresses.get(user)

        if user_address and user != self.login_username:
            ip_address, _port = user_address
            country_code = self.geoip.get_country_code(ip_address)
            return country_code

        if user not in self.ip_requested:
            self.queue.append(slskmessages.GetPeerAddress(user))

        return None

    def watch_user(self, user, force_update=False):
        """ Tell the server we want to be notified of status/stat updates
        for a user """

        if self.user_status == slskmessages.UserStatus.OFFLINE:
            return

        if not force_update and user in self.watched_users:
            # Already being watched, and we don't need to re-fetch the status/stats
            return

        self.queue.append(slskmessages.AddUser(user))

        # Get privilege status
        self.queue.append(slskmessages.GetUserStatus(user))

        self.watched_users.add(user)

    """ Message Callbacks """

    def thread_callback(self, _msgs):  # pylint: disable=method-hidden
        # Overridden by the frontend to call process_thread_callback in the main thread
        pass

    def process_thread_callback(self, msgs):

        for msg in msgs:
            if self.shutdown:
                return

            try:
                self.message_callbacks[msg.__class__](msg)

            except KeyError:
                log.add("No handler for class %s %s", (msg.__class__, dir(msg)))

        msgs.clear()

    def scheduler_callback(self, msg):
        msg.callback()

    @staticmethod
    def dummy_message(msg):
        # Ignore received message
        pass

    def cli_command(self, msg):
        self.pluginhandler.trigger_cli_command_event(msg.command, msg.args or "")

    def show_connection_error_message(self, msg):
        """ Request UI to show error messages related to connectivity """

        for i in msg.msgs:
            if i.__class__ in (slskmessages.TransferRequest, slskmessages.FileUploadInit):
                self.transfers.get_cant_connect_upload(msg.user, i.token, msg.offline)

            elif i.__class__ is slskmessages.QueueUpload:
                self.transfers.get_cant_connect_queue_file(msg.user, i.file, msg.offline)

            elif i.__class__ is slskmessages.GetSharedFileList:
                self.userbrowse.show_connection_error(msg.user)

            elif i.__class__ is slskmessages.UserInfoRequest:
                self.userinfo.show_connection_error(msg.user)

    def peer_message_progress(self, msg):

        if msg.msg_type is slskmessages.SharedFileList:
            self.userbrowse.peer_message_progress(msg)

        elif msg.msg_type is slskmessages.UserInfoReply:
            self.userinfo.peer_message_progress(msg)

    def peer_connection_closed(self, msg):
        self.userbrowse.peer_connection_closed(msg)
        self.userinfo.peer_connection_closed(msg)

    def server_timeout(self, _msg):
        if not config.need_config():
            self.connect()

    def server_disconnect(self, msg=None):

        self.user_status = slskmessages.UserStatus.OFFLINE

        # Clean up connections
        self.user_statuses.clear()
        self.watched_users.clear()

        self.pluginhandler.server_disconnect_notification(msg.manual_disconnect if msg else True)

        self.shares.server_disconnect()
        self.transfers.server_disconnect()
        self.search.server_disconnect()
        self.userlist.server_disconnect()
        self.chatrooms.server_disconnect()
        self.privatechat.server_disconnect()
        self.userinfo.server_disconnect()
        self.userbrowse.server_disconnect()
        self.interests.server_disconnect()
        self.ui_callback.server_disconnect()

        self.login_username = None

    def set_connection_stats(self, msg):
        self.ui_callback.set_connection_stats(msg)

    def login(self, msg):
        """ Server code: 1 """

        if msg.success:
            self.user_status = slskmessages.UserStatus.ONLINE
            self.login_username = msg.username

            self.set_away_mode(config.sections["server"]["away"])
            self.watch_user(msg.username)

            if msg.ip_address is not None:
                self.user_ip_address = msg.ip_address

            self.transfers.server_login()
            self.search.server_login()
            self.userbrowse.server_login()
            self.userinfo.server_login()
            self.userlist.server_login()
            self.privatechat.server_login()
            self.chatrooms.server_login()
            self.ui_callback.server_login()

            if msg.banner:
                log.add(msg.banner)

            self.interests.server_login()
            self.shares.send_num_shared_folders_files()

            self.queue.append(slskmessages.PrivateRoomToggle(config.sections["server"]["private_chatrooms"]))
            self.pluginhandler.server_connect_notification()

        else:
            if msg.reason == slskmessages.LoginFailure.PASSWORD:
                self.ui_callback.invalid_password()
                return

            log.add(_("Unable to connect to the server. Reason: %s"), msg.reason, title=_("Cannot Connect"))

    def get_peer_address(self, msg):
        """ Server code: 3 """

        user = msg.user

        # If the IP address changed, make sure our IP block/ignore list reflects this
        self.network_filter.update_saved_user_ip_filters(user)

        if self.network_filter.block_unblock_user_ip_callback(user):
            return

        if self.network_filter.ignore_unignore_user_ip_callback(user):
            return

        country_code = self.geoip.get_country_code(msg.ip_address)

        self.chatrooms.set_user_country(user, country_code)
        self.userinfo.set_user_country(user, country_code)
        self.userlist.set_user_country(user, country_code)

        # From this point on all paths should call
        # self.pluginhandler.user_resolve_notification precisely once
        self.privatechat.private_message_queue_process(user)

        if user not in self.ip_requested:
            self.pluginhandler.user_resolve_notification(user, msg.ip_address, msg.port)
            return

        self.ip_requested.remove(user)
        self.pluginhandler.user_resolve_notification(user, msg.ip_address, msg.port, country_code)

        if country_code:
            country = " (%(cc)s / %(country)s)" % {
                'cc': country_code, 'country': self.geoip.country_code_to_name(country_code)}
        else:
            country = ""

        if msg.ip_address == "0.0.0.0":
            log.add(_("Cannot retrieve the IP of user %s, since this user is offline"), user)
            return

        log.add(_("IP address of user %(user)s: %(ip)s, port %(port)i%(country)s"), {
            'user': user,
            'ip': msg.ip_address,
            'port': msg.port,
            'country': country
        }, title=_("IP Address"))

    def add_user(self, msg):
        """ Server code: 5 """

        if msg.userexists:
            self.get_user_stats(msg)
            return

        # User does not exist, server will not keep us informed if the user is created later
        self.watched_users.discard(msg.user)

    def get_user_status(self, msg):
        """ Server code: 7 """

        user = msg.user
        status = msg.status
        privileged = msg.privileged

        if privileged is not None:
            if privileged:
                self.transfers.add_to_privileged(user)
            else:
                self.transfers.remove_from_privileged(user)

        if status not in (slskmessages.UserStatus.OFFLINE, slskmessages.UserStatus.ONLINE,
                          slskmessages.UserStatus.AWAY):
            log.add_debug("Received an unknown status %(status)s for user %(user)s from the server", {
                "status": status,
                "user": user
            })
            return

        # We get status updates for room users even if we don't watch them
        self.chatrooms.get_user_status(msg)

        if user in self.watched_users:
            self.user_statuses[user] = status

            self.transfers.get_user_status(msg)
            self.interests.get_user_status(msg)
            self.userbrowse.get_user_status(msg)
            self.userinfo.get_user_status(msg)
            self.userlist.get_user_status(msg)
            self.privatechat.get_user_status(msg)

        self.pluginhandler.user_status_notification(user, status, privileged)

    def connect_to_peer(self, msg):
        """ Server code: 18 """

        if msg.privileged is None:
            return

        if msg.privileged:
            self.transfers.add_to_privileged(msg.user)
        else:
            self.transfers.remove_from_privileged(msg.user)

    def get_user_stats(self, msg):
        """ Server code: 36 """

        user = msg.user

        if user == self.login_username:
            self.transfers.upload_speed = msg.avgspeed

        # We get stat updates for room users even if we don't watch them
        self.chatrooms.get_user_stats(msg)

        if user in self.watched_users:
            self.interests.get_user_stats(msg)
            self.userinfo.get_user_stats(msg)
            self.userlist.get_user_stats(msg)

        stats = {
            'avgspeed': msg.avgspeed,
            'uploadnum': msg.uploadnum,
            'files': msg.files,
            'dirs': msg.dirs,
        }

        self.pluginhandler.user_stats_notification(user, stats)

    @staticmethod
    def admin_message(msg):
        """ Server code: 66 """

        log.add(msg.msg, title=_("Soulseek Announcement"))

    def privileged_users(self, msg):
        """ Server code: 69 """

        self.transfers.set_privileged_users(msg.users)
        log.add(_("%i privileged users"), (len(msg.users)))

    def add_to_privileged(self, msg):
        """ Server code: 91 """
        """ DEPRECATED """

        self.transfers.add_to_privileged(msg.user)

    def check_privileges(self, msg):
        """ Server code: 92 """

        mins = msg.seconds // 60
        hours = mins // 60
        days = hours // 24

        if msg.seconds == 0:
            log.add(_("You have no Soulseek privileges. Privileges are not required, but allow your downloads "
                      "to be queued ahead of non-privileged users."))
        else:
            log.add(_("%(days)i days, %(hours)i hours, %(minutes)i minutes, %(seconds)i seconds of "
                      "Soulseek privileges left"), {
                'days': days,
                'hours': hours % 24,
                'minutes': mins % 60,
                'seconds': msg.seconds % 60
            })

        self.privileges_left = msg.seconds

    @staticmethod
    def change_password(msg):
        """ Server code: 142 """

        password = msg.password
        config.sections["server"]["passw"] = password
        config.write_configuration()

        log.add(_("Your password has been changed"), title=_("Password Changed"))


core = Core()