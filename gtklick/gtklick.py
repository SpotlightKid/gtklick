#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# gtklick
#
# Copyright (C) 2008-2010  Dominic Sacré  <dominic.sacre@gmx.de>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import, print_function, unicode_literals

import builtins
import getopt
import gettext
import locale
import os
import sys
import weakref

builtins._ = gettext.gettext

try:
    from gi import pygtkcompat
except ImportError:
    import pygtk
    pygtk.require('2.0')
else:
    pygtkcompat.enable()
    pygtkcompat.enable_gtk(version='3.0')

import gobject
import gtk

try:
    import gtk.glade
    HAVE_GLADE = True
except ImportError:
    from gi.repository import Gtk
    HAVE_GLADE = False

from . import klick_backend
from . import gtklick_config
from . import main_window
from . import misc
from . import preferences_dialog
from . import profiles_pane


class GTKlick:
    def __init__(self, args, share_dir, locale_dir):
        try:
            locale.setlocale(locale.LC_ALL, '')
        except locale.Error:
            # don't crash when run with unsupported locale
            pass

        gettext.bindtextdomain('gtklick', locale_dir)
        gettext.textdomain('gtklick')

        if HAVE_GLADE:
            gtk.glade.bindtextdomain('gtklick', locale_dir)
            gtk.glade.textdomain('gtklick')

        self.config = None
        self.parse_cmdline(args)

        gtk.gdk.threads_init()

        try:
            self.setup(share_dir)
            if not self.connect:
                self.restore_config()
            else:
                self.query_config()
        except klick_backend.KlickBackendError as e:
            self.error_message(e.msg)
            sys.exit(1)

        # start timer to check if klick is still running
        if self.klick.process:
            self.timer = gobject.timeout_add(1000, misc.weakref_method(self.check_klick))

    def __del__(self):
        if self.config:
            self.config.write()

    # parse command line arguments
    def parse_cmdline(self, args):
        self.port = None
        self.return_port = None
        self.connect = False
        self.verbose = False
        try:
            r = getopt.getopt(args, 'o:q:r:Lh');
            for opt, arg in r[0]:
                if opt == '-o':
                    self.port = arg
                    self.connect = False
                elif opt == '-q':
                    self.port = arg
                    self.connect = True
                elif opt == '-r':
                    self.return_port = arg
                elif opt == '-L':
                    self.verbose = True
                elif opt == '-h':
                    self.print_help()
                    sys.exit(0)
        except getopt.GetoptError as e:
            sys.exit(e.msg)

    def print_help(self):
        print(_("Usage:\n" \
                "  gtklick [ options ]\n" \
                "\n" \
                "Options:\n" \
                "  -o port   OSC port to start klick with\n" \
                "  -q port   OSC port of running klick instance to connect to\n" \
                "  -r port   OSC port to be used for gtklick\n" \
                "  -h        show this help"))

    # create windows, config, and klick backend
    def setup(self, share_dir):
        if HAVE_GLADE:
            self.wtree = gtk.glade.XML(os.path.join(share_dir, 'gtklick.glade'))
        else:
            self.wtree = gtk.Builder()
            self.wtree.add_from_file(os.path.join(share_dir, 'gtklick.ui'))

        # explicitly call base class method, because get_name() is overridden in AboutDialog. stupid GTK...
        if HAVE_GLADE:
            self.widgets = dict([(gtk.Widget.get_name(w), w)
                                 for w in self.wtree.get_widget_prefix('')])
        else:
            self.widgets = dict([(w.get_name(w), w)
                                 for w in self.wtree.get_objects()
                                 if isinstance(w, gtk.Widget)])
            print(self.widgets)


        self.config = gtklick_config.GTKlickConfig()

        # load config from file
        self.config.read()

        # start klick process
        self.klick = klick_backend.KlickBackend('gtklick', self.port, self.return_port, self.connect, self.verbose)

        # make "globals" known in other modules
        for m in (main_window, profiles_pane, preferences_dialog):
            m.wtree = self.wtree
            m.widgets = self.widgets
            m.klick = weakref.proxy(self.klick)
            m.config = weakref.proxy(self.config)

        # the actual windows are created by glade, this basically just connects GUI and OSC callbacks
        self.win = main_window.MainWindow()
        self.profiles = profiles_pane.ProfilesPane(self.win)
        self.prefs = preferences_dialog.PreferencesDialog()

        #self.klick.add_method(None, None, self.fallback)

    # restore settings from config file.
    # many settings are just sent to klick, and the OSC notifications will take care of the rest
    def restore_config(self):
        # port connections
        if len(self.config.prefs_connect_ports):
            ports = self.config.prefs_connect_ports.split('\0')
            for p in ports:
                self.prefs.model_ports.append([p])
        else:
            ports = []

        if self.config.prefs_autoconnect:
            misc.do_quietly(lambda: self.widgets['radio_connect_auto'].set_active(True))
            self.klick.send('/config/autoconnect')
        else:
            misc.do_quietly(lambda: self.widgets['radio_connect_manual'].set_active(True))
            self.klick.send('/config/connect', *ports)

        # sound / volume
        if self.config.prefs_sound >= 0:
            self.klick.send('/config/set_sound', self.config.prefs_sound)
        else:
            self.klick.send('/config/set_sound', self.config.prefs_sound_accented, self.config.prefs_sound_normal)

        self.klick.send('/config/set_sound_pitch',
            2 ** (self.config.prefs_pitch_accented / 12.0),
            2 ** (self.config.prefs_pitch_normal / 12.0)
        )
        self.klick.send('/config/set_volume', self.config.volume)

        # metronome state
        misc.do_quietly(lambda: (
            self.widgets['check_speedtrainer_enable'].set_active(self.config.speedtrainer),
            self.widgets['spin_tempo_increment'].set_value(self.config.tempo_increment),
            self.widgets['radio_meter_other'].set_active(self.config.denom != 0)
        ))
        self.widgets['spin_tempo_increment'].set_sensitive(self.config.speedtrainer)
        self.widgets['spin_tempo_start'].set_sensitive(self.config.speedtrainer)

        self.klick.send('/simple/set_tempo', self.config.tempo)
        self.klick.send('/simple/set_tempo_increment', self.config.tempo_increment if self.config.speedtrainer else 0.0)
        self.klick.send('/simple/set_tempo_start', self.config.tempo_start)
        self.klick.send('/simple/set_meter', self.config.beats, self.config.denom if self.config.denom else 4)
        self.klick.send('/simple/set_pattern', self.config.pattern)

    # get current settings from running klick instance
    def query_config(self):
        self.klick.send('/query')

    # start the whole thing
    def run(self):
        self.widgets['window_main'].show()
        gtk.gdk.threads_enter()
        gtk.main()
        gtk.gdk.threads_leave()

    # check if klick is still running
    def check_klick(self):
        if not self.klick.check_process():
            self.error_message(_("klick seems to have been killed, can't continue without it"))
            sys.exit(1)
        return True

    def fallback(self, path, args, types, src):
        print("message not handled:", path, args, src.get_url())

    def error_message(self, msg):
        m = gtk.MessageDialog(self.wtree.get_widget('window_main'), 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_OK, msg)
        m.set_title(_("gtklick error"))
        m.run()
        m.destroy()


if __name__ == '__main__':
    app = GTKlick(sys.argv[1:], 'share', 'build/locale')
    app.run()
