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

from __future__ import print_function, unicode_literals

import inspect
import weakref

try:
    from new import instancemethod
except ImportError:
    from types import MethodType as instancemethod

import gobject
import gtk
import gtk.keysyms


block = False


# decorator: don't call function while gtk signals are blocked
def gui_callback(f):
    def g(self, *args):
        global block
        # FIXME: it may be a bad idea to discard arbitrary signals
        if not block:
            return f(self, *args)
    return g

# decorator: enclose the function in threads_enter() / threads_leave() to safely call
# gtk functions, and block gtk signals while the function is running
def osc_callback(f):
    def g(self, *args):
        global block
        try:
            gtk.gdk.threads_enter()
            block = True

            #print(args[0], args[1])

            # call function with the correct number of arguments, to allow osc callbacks to omit
            # some of pyliblo's callback arguments
            if inspect.getargspec(f)[1] == None:
                n = len(inspect.getargspec(f)[0]) - 1
                r = f(self, *args[0:n])
            else:
                r = f(self, *args)

            return r
        finally:
            block = False
            gtk.gdk.threads_leave()
    return g


# block gtk signals while calling function f
def do_quietly(f):
    global block
    try:
        block = True
        return f()
    finally:
        block = False


class weakref_method:
    def __init__(self, f):
        self.inst = weakref.ref(getattr(f, '__self__', f.im_self))
        self.func = getattr(f, '__func__', f.im_func)
    def __call__(self, *args, **kwargs):
        f = instancemethod(self.func, self.inst(), self.inst().__class__)
        return f(*args, **kwargs)


# calls function once when going idle, blocking redundant calls
class run_idle_once:
    def __init__(self, call):
        self.call = call
        self.pending = False
    def queue(self):
        if not self.pending:
            self.pending = True
            gobject.idle_add(self.call_wrapper)
    def call_wrapper(self):
        self.pending = False
        self.call()
        return False


class TristateCheckButton(gtk.CheckButton):
    def __init__(self, label):
        gtk.CheckButton.__init__(self, label)
        self.connect('button-release-event', self.on_button_released)
        self.connect('key-press-event', self.on_key_pressed)

    def get_state(self):
        if self.get_inconsistent():
            return 1
        elif self.get_active():
            return 2
        else:
            return 0

    def set_state(self, state):
        toggle = self.get_inconsistent() != (state == 1) and self.get_active() == (state != 0)
        self.set_inconsistent(state == 1)
        self.set_active(state != 0)
        if toggle:
            # emit "toggled" manually if "active" didn't change, but "inconsistent" did
            self.toggled()

    def on_button_released(self, b, ev):
        s = ev.get_state()
        if s & gtk.gdk.CONTROL_MASK:
            if s & gtk.gdk.BUTTON1_MASK:
                self.set_state(2)
            elif s & gtk.gdk.BUTTON2_MASK:
                self.set_state(1)
            elif s & gtk.gdk.BUTTON3_MASK:
                self.set_state(0)
        else:
            if s & gtk.gdk.BUTTON1_MASK:
                self.set_state((self.get_state() - 1) % 3)
            elif s & gtk.gdk.BUTTON2_MASK:
                self.set_state(1 if self.get_state() == 2 else 2)
            elif s & gtk.gdk.BUTTON3_MASK:
                self.set_state(1 if self.get_state() == 0 else 0)
        self.queue_draw()
        return True

    def on_key_pressed(self, b, ev):
        if ev.keyval == gtk.keysyms.space:
            self.set_state((self.get_state() - 1) % 3)
            self.queue_draw()
            return True
        else:
            return False


def treeview_remove(model, selection, i):
    path = model.get_path(i)
    model.remove(i)

    # select next item
    selection.select_path(path)
    if not selection.path_is_selected(path):
        row = path[0]-1
        if row >= 0:
            selection.select_path(row)
