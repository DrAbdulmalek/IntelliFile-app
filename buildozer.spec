# ⚠️ EXPERIMENTAL — NOT PART OF PRODUCT CORE
# This file is kept for historical reference only. IntelliFile is a
# desktop-first local file manager. Android/Kivy is NOT the product
# direction. See mobile/README.md for details. Do NOT rely on this
# spec for releases.

[app]
title = IntelliFile Manager
package.name = intellifile
package.domain = org.intellifile
source.dir = mobile
source.include_exts = py,png,jpg,kv,atlas,json,ttf,otf
version = 2.1.0
requirements = python3,kivy==2.2.1
orientation = portrait
fullscreen = 1
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,CAMERA,RECORD_AUDIO
android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a
android.allow_backup = True
android.skip_update = False
p4a.branch = v2024.01.21
log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
warn_on_root = 1
