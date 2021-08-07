# -*- coding: utf-8 -*-
'''
Common functions for EmailClient
'''
from __future__ import print_function
from Tools.Directories import resolveFilename, SCOPE_LANGUAGE, SCOPE_PLUGINS, SCOPE_SKIN_IMAGE
from Components.Language import language
from Components.config import config
import os
import gettext
import time

PluginLanguageDomain = "EmailClient"
PluginLanguagePath = "Extensions/EmailClient/locale/"


def localeInit():
	gettext.bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))


def _(txt):
	if gettext.dgettext(PluginLanguageDomain, txt):
		return gettext.dgettext(PluginLanguageDomain, txt)
	else:
		print("[" + PluginLanguageDomain + "] fallback to default translation for " + txt)
		return gettext.gettext(txt)


language.addCallback(localeInit())


def initLog():
	try:
		os.remove("/tmp/EmailClient.log")
	except OSError:
		pass


def debug(message):
	if config.plugins.emailimap.debug.value:
		try:
			deb = open("/tmp/EmailClient.log", "aw")
			deb.write(time.ctime() + ': ' + message + "\n")
			deb.close()
		except Exception as e:
			debug("%s (retried debug: %s)" % (repr(message), str(e)))


from enigma import getDesktop
DESKTOP_WIDTH = getDesktop(0).size().width()
DESKTOP_HEIGHT = getDesktop(0).size().height()


def scaleH(y2, y1):
	if y2 == -1:
		y2 = y1 * 1280 / 720
	elif y1 == -1:
		y1 = y2 * 720 / 1280
	return scale(y2, y1, 1280, 720, DESKTOP_WIDTH)


def scaleV(y2, y1):
	if y2 == -1:
		y2 = y1 * 720 / 576
	elif y1 == -1:
		y1 = y2 * 576 / 720
	return scale(y2, y1, 720, 576, DESKTOP_HEIGHT)


def scale(y2, y1, x2, x1, x):
	return (y2 - y1) * (x - x1) / (x2 - x1) + y1
