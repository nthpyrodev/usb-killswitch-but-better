
# USB Kill Switch

This tool will execute chosen actions when a change in USB devices is detected.

~~Linux is not fully supported yet.~~ I have completeley pivoted for the nth time. If you're using Windows, then you should consider switching to Linux. ~~While I do plan to carry on with the Windows version, I'm going to be primarily focusing on the Linux version.~~ Just use Linux. Keep in mind that some features have not been properly tested, and should not be relied upon. Please test before relying on this tool. The rest of the readme is outdated, so ignore it for now, until I update it.

## How to run

Prerequisites:
- Python installed
- Sudo for some options

Put the Python script anywhere you want. It will detect any type of change, whether it be storage, periphals, etc, and trigger the killswitch. This is useful if a mouse jiggler is inserted to keep the computer awake, etc.
## Features

- Dismount VeraCrypt volumes
- End specified processes
- Delete or overwrite specified files
- Turn off screen
- Lock OS
- Shutdown
- Execute custom commands such as `python3 something.py` or any command that can be run on Linux
- Trigger killswitch on any device change
- Button must be pressed 5 times to disarm any killswitch, to avoid accidental or forced presses.
- Log for viewing changes.
## Notes

If the killswitch gets triggered, then you must disarm then rearm again to reactivate it.

# Contributing

Contributors are welcome, even if the changes are minor, or even just improving the ReadMe.


![image](https://github.com/user-attachments/assets/d6c5d20b-e791-4cc7-b974-ed07a69ac433)
![image](https://github.com/user-attachments/assets/3a292a4a-599e-4b42-a642-0a98b7ccc008)


