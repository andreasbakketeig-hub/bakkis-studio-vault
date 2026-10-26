"""
Write the Finder quick action "Prepare for collab" (an Automator workflow).

    .venv/bin/python tools/make_quick_action.py

Right-click a Live project folder or .als file in Finder › Quick Actions › Prepare for collab: it opens the
project in BAKKIS STUDIO VAULT's Handoff (the app's "Open with" handling does the rest). The workflow is a
"Run Shell Script" action with one line; nothing else runs. It is shipped inside the app and installed from
Settings into ~/Library/Services.
"""

from __future__ import annotations

import plistlib
import uuid
from pathlib import Path

NAME = "Prepare for collab"
APP = "BAKKIS STUDIO VAULT"
DEST = Path(__file__).resolve().parents[1] / "studio_vault" / "finder" / f"{NAME}.workflow" / "Contents"
COMMAND = f'open -a "{APP}" "$@"\n'


def workflow() -> dict:
    return {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [{
            "action": {
                "AMAccessoryParameters": {},
                "AMActionVersion": "2.0.3",
                "AMApplication": ["Automator"],
                "AMParameterProperties": {
                    "COMMAND_STRING": {}, "CheckedForUserDefaultShell": {}, "inputMethod": {}, "shell": {}, "source": {},
                },
                "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
                "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                "ActionName": "Run Shell Script",
                "ActionParameters": {
                    "COMMAND_STRING": COMMAND,
                    "CheckedForUserDefaultShell": True,
                    "inputMethod": 1,          # input as arguments ("$@")
                    "shell": "/bin/bash",
                    "source": "",
                },
                "BundleIdentifier": "com.apple.RunShellScript",
                "CFBundleVersion": "2.0.3",
                "CanShowSelectedItemsWhenRun": False,
                "CanShowWhenRun": True,
                "Category": ["AMCategoryUtilities"],
                "Class Name": "RunShellScriptAction",
                "InputUUID": str(uuid.uuid4()).upper(),
                "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
                "OutputUUID": str(uuid.uuid4()).upper(),
                "UUID": str(uuid.uuid4()).upper(),
                "UnlocalizedApplications": ["Automator"],
                "arguments": {
                    "0": {"default value": 0, "name": "inputMethod", "required": "0", "type": 0, "uuid": "0"},
                    "1": {"default value": False, "name": "CheckedForUserDefaultShell", "required": "0", "type": 0, "uuid": "1"},
                    "2": {"default value": "", "name": "source", "required": "0", "type": 0, "uuid": "2"},
                    "3": {"default value": "", "name": "COMMAND_STRING", "required": "0", "type": 0, "uuid": "3"},
                    "4": {"default value": "/bin/sh", "name": "shell", "required": "0", "type": 0, "uuid": "4"},
                },
                "isViewVisible": True,
                "location": "309.000000:253.000000",
                "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
            },
            "isViewVisible": True,
        }],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 11,
            "processesInput": 0,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def info() -> dict:
    return {"NSServices": [{
        "NSBackgroundColorName": "background",
        "NSIconName": "NSActionTemplate",
        "NSMenuItem": {"default": NAME},
        "NSMessage": "runWorkflowAsService",
        "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
        "NSSendFileTypes": ["public.item"],
    }]}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "document.wflow").open("wb") as fh:
        plistlib.dump(workflow(), fh)
    with (DEST / "Info.plist").open("wb") as fh:
        plistlib.dump(info(), fh)
    print(DEST.parent)


if __name__ == "__main__":
    main()
