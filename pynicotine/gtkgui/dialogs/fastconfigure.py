# COPYRIGHT (C) 2020-2021 Nicotine+ Team
# COPYRIGHT (C) 2016-2017 Michael Labouebe <gfarmerfr@free.fr>
# COPYRIGHT (C) 2009-2011 Quinox <quinox@users.sf.net>
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

import os

from gi.repository import Gtk

from pynicotine.config import config
from pynicotine.gtkgui.widgets.filechooser import FileChooserButton
from pynicotine.gtkgui.widgets.filechooser import FolderChooser
from pynicotine.gtkgui.widgets.dialogs import dialog_show
from pynicotine.gtkgui.widgets.dialogs import set_dialog_properties
from pynicotine.gtkgui.widgets.theme import get_icon
from pynicotine.gtkgui.widgets.treeview import initialise_columns
from pynicotine.gtkgui.widgets.ui import UserInterface
from pynicotine.utils import open_uri


class FastConfigure(UserInterface):

    def __init__(self, frame, core):

        super().__init__("ui/dialogs/fastconfigure.ui")

        self.frame = frame
        self.core = core
        set_dialog_properties(self.dialog, frame.MainWindow)

        for page in (self.welcome_page, self.account_page, self.port_page, self.share_page, self.summary_page):
            self.dialog.append_page(page)

            if Gtk.get_major_version() == 3:
                self.dialog.child_set_property(page, "has-padding", False)

        self.dialog.set_page_type(self.welcome_page, Gtk.AssistantPageType.CUSTOM)
        self.dialog.set_page_type(self.summary_page, Gtk.AssistantPageType.SUMMARY)

        logo = get_icon("n")

        if logo:
            self.main_icon.set_property("gicon", logo)
        else:
            self.main_icon.set_property("icon-name", config.application_id)

        # Page specific, share_page
        self.download_folder_button = FileChooserButton(
            self.download_folder_button, self.dialog, "folder")

        self.shared_folders = None
        self.sharelist = Gtk.ListStore(
            str,
            str
        )

        self.column_numbers = list(range(self.sharelist.get_n_columns()))
        initialise_columns(
            frame, None, self.shares_list_view,
            ["virtual_folder", _("Virtual Folder"), 0, "text", None],
            ["folder", _("Folder"), 0, "text", None]
        )

        self.shares_list_view.set_model(self.sharelist)

    def show(self):

        if config.need_config():
            self.cancel_button.hide()

        # account_page
        self.username_entry.set_text(config.sections["server"]["login"])
        self.password_entry.set_text(config.sections["server"]["passw"])

        # port_page
        url = config.portchecker_url % str(self.core.protothread.listenport)
        text = "<a href='" + url + "' title='" + url + "'>" + _("Check Port Status") + "</a>"
        self.check_port_label.set_markup(text)
        self.check_port_label.connect("activate-link", lambda x, url: open_uri(url))

        # share_page
        self.shared_folders = config.sections["transfers"]["shared"][:]

        if config.sections['transfers']['downloaddir']:
            self.download_folder_button.set_path(
                config.sections['transfers']['downloaddir']
            )

        self.sharelist.clear()

        for entry in self.shared_folders:
            virtual_name, path = entry
            self.sharelist.insert_with_valuesv(-1, self.column_numbers, [str(virtual_name), str(path)])

        # completepage
        import urllib.parse

        login = urllib.parse.quote(config.sections["server"]["login"])
        url = config.privileges_url % login
        text = "<a href='" + url + "' title='" + url + "'>" + _("Get Soulseek Privileges…") + "</a>"
        self.privileges_label.set_markup(text)
        self.privileges_label.connect("activate-link", lambda x, url: open_uri(url))

        dialog_show(self.dialog)

    def reset_completeness(self):
        """ Turns on the complete flag if everything required is filled in. """

        complete = False
        pageid = self.dialog.get_current_page()
        page = self.dialog.get_nth_page(pageid)

        if not page:
            return

        if page in (self.welcome_page, self.port_page, self.summary_page):
            complete = True

        elif page == self.account_page:
            if len(self.username_entry.get_text()) > 0 and len(self.password_entry.get_text()) > 0:
                complete = True

        elif page == self.share_page:
            if self.download_folder_button.get_path():
                complete = True

        self.dialog.set_page_complete(page, complete)

    def on_entry_changed(self, *_args):
        self.reset_completeness()

    def on_add_share_selected(self, selected, _data):

        shared = config.sections["transfers"]["shared"]
        buddy_shared = config.sections["transfers"]["buddyshared"]

        for folder in selected:

            # If the folder is already shared
            if folder in (x[1] for x in shared + buddy_shared):
                return

            virtual = os.path.basename(os.path.normpath(folder))

            # Remove slashes from share name to avoid path conflicts
            virtual = virtual.replace('/', '_').replace('\\', '_')
            virtual_final = virtual

            counter = 1
            while virtual_final in (x[0] for x in shared + buddy_shared):
                virtual_final = virtual + str(counter)
                counter += 1

            # The share is unique: we can add it
            self.sharelist.insert_with_valuesv(-1, self.column_numbers, [virtual, folder])
            self.shared_folders.append((virtual, folder))

    def on_add_share(self, *_args):

        FolderChooser(
            parent=self.dialog,
            title=_("Add a Shared Folder"),
            callback=self.on_add_share_selected,
            multiple=True
        ).show()

    def on_remove_share(self, *_args):

        model, paths = self.shares_list_view.get_selection().get_selected_rows()

        for path in reversed(paths):
            model.remove(model.get_iter(path))

    def on_set_up(self, *_args):
        self.dialog.next_page()
        self.username_entry.grab_focus()

    def on_prepare(self, *_args):
        self.reset_completeness()

    def on_close(self, *_args):

        # account_page
        config.sections["server"]["login"] = self.username_entry.get_text()
        config.sections["server"]["passw"] = self.password_entry.get_text()

        # share_page
        config.sections['transfers']['downloaddir'] = self.download_folder_button.get_path()
        config.sections["transfers"]["shared"] = self.shared_folders

        # Rescan shares
        self.core.shares.rescan_shares()
        self.core.connect()

        self.dialog.destroy()

    def on_cancel(self, *_args):
        self.dialog.destroy()
