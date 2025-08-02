import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import subprocess
import threading
import time
import os
import sys
import pyudev

selectedTasks = []
customCommands = []
fileToDelete = ""
processesToKill = []
usbMonitoring = False
usbDevices = []
usbPauseCounter = 0
usbTimeout = 15
veracryptTimeout = 30
shutdownMode = "immediate"
volumesToDismount = []
shredPasses = 7
systemVolumesCache = []
nonSystemVolumesCache = []
lastCacheUpdate = 0

def getCurrentUsbDevices():
    devices = []
    try:
        context = pyudev.Context()
        for device in context.list_devices(subsystem='block', DEVTYPE='disk'):
            if device.get('ID_BUS') == 'usb':
                devices.append(f"USB_DISK:{device.device_node}")
        
        for device in context.list_devices(subsystem='usb', DEVTYPE='usb_device'):
            devices.append(f"USB_DEV:{device.get('ID_VENDOR_ID', '')}:{device.get('ID_MODEL_ID', '')}")
    
    except Exception as e:
        logMessage(f"Error getting USB devices with pyudev: {str(e)}")
        try:
            result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                devices = result.stdout.splitlines()
        except:
            pass
    
    return devices

def checkUsbChanges():
    global usbDevices
    try:
        currentDevices = getCurrentUsbDevices()
        if set(currentDevices) != set(usbDevices):
            usbDevices = currentDevices
            return True
        return False
    except Exception as e:
        logMessage(f"Error checking USB changes: {str(e)}")
        return False

def getMountedUsbVolumes():
    mountedVolumes = []
    try:
        context = pyudev.Context()
        
        for device in context.list_devices(subsystem='block'):
            if device.get('ID_BUS') == 'usb' and device.get('DEVTYPE') in ['disk', 'partition']:
                device_node = device.device_node
                if device_node:
                    try:
                        with open('/proc/mounts', 'r') as f:
                            for line in f:
                                if line.startswith(device_node):
                                    parts = line.split()
                                    if len(parts) >= 2:
                                        mount_point = parts[1]
                                        mountedVolumes.append((device_node, mount_point))
                                    break
                    except:
                        continue
    
    except Exception as e:
        logMessage(f"Error getting mounted USB volumes with pyudev: {str(e)}")
        try:
            result = subprocess.run(["mount"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if any(pattern in line for pattern in ["/dev/sd", "/dev/usb", "/media", "/run/media"]):
                        parts = line.split(" ")
                        if len(parts) >= 3:
                            device = parts[0]
                            mountPoint = parts[2]
                            mountedVolumes.append((device, mountPoint))
        except:
            pass
    
    return mountedVolumes

def isSystemVolume(device, mountPoint):
    global systemVolumesCache, nonSystemVolumesCache, lastCacheUpdate
    
    cacheAge = time.time() - lastCacheUpdate
    if cacheAge < 60: # Cache valid for 60 seconds, I should reconsider this
        if device in systemVolumesCache or mountPoint in systemVolumesCache:
            return True
        if device in nonSystemVolumesCache and mountPoint in nonSystemVolumesCache:
            return False
    
    criticalMounts = ['/', '/boot', '/home', '/var', '/usr', '/etc', '/bin', '/sbin']
    if mountPoint in criticalMounts:
        systemVolumesCache.append(device)
        systemVolumesCache.append(mountPoint)
        lastCacheUpdate = time.time()
        return True
    
    try:
        fstabResult = subprocess.run(["grep", device, "/etc/fstab"], 
                                     capture_output=True, text=True, timeout=5)
        if fstabResult.returncode == 0 and fstabResult.stdout.strip():
            systemVolumesCache.append(device)
            systemVolumesCache.append(mountPoint)
            lastCacheUpdate = time.time()
            return True
    except:
        pass
    
    try:
        if any(fs in mountPoint for fs in ['nfs', 'cifs', 'smb']):
            systemVolumesCache.append(device)
            systemVolumesCache.append(mountPoint)
            lastCacheUpdate = time.time()
            return True
            
        if ('/media/' in mountPoint or '/run/media/' in mountPoint) and '/dev/sd' in device:
            nonSystemVolumesCache.append(device)
            nonSystemVolumesCache.append(mountPoint)
            lastCacheUpdate = time.time()
            return False
    except:
        pass
    
    systemVolumesCache.append(device)
    systemVolumesCache.append(mountPoint)
    lastCacheUpdate = time.time()
    return True

def updateVolumeCache():
    global systemVolumesCache, nonSystemVolumesCache, lastCacheUpdate
    
    try:
        systemVolumesCache = []
        nonSystemVolumesCache = []
        
        mountedVolumes = getMountedUsbVolumes()
        for device, mountPoint in mountedVolumes:
            isSystemVolume(device, mountPoint)
            
        lastCacheUpdate = time.time()
        logMessage("Volume cache updated")
    except Exception as e:
        logMessage(f"Error updating volume cache: {str(e)}")

def dismountUsbVolumes():
    try:
        logMessage("Attempting to dismount USB volumes...")
        dismountThread = threading.Thread(target=dismountUsbVolumesTask)
        dismountThread.daemon = True
        dismountThread.start()
        
        dismountThread.join(timeout=usbTimeout)
        
        if dismountThread.is_alive():
            logMessage(f"USB volume dismounting taking too long (>{usbTimeout}s). Proceeding with next actions.")
            return False
        return True
    except Exception as e:
        logMessage(f"Error during USB volume dismount: {str(e)}")
        return False

def dismountUsbVolumesTask():
    try:
        mountedVolumes = getMountedUsbVolumes()
        
        if volumesToDismount:
            for device, mountPoint in mountedVolumes:
                if device in volumesToDismount or mountPoint in volumesToDismount:
                    dismountVolume(device, mountPoint)
        else:
            for device, mountPoint in mountedVolumes:
                if not isSystemVolume(device, mountPoint):
                    dismountVolume(device, mountPoint)
    except Exception as e:
        logMessage(f"Error in dismount task: {str(e)}")

def dismountVolume(device, mountPoint):
    try:
        logMessage(f"Dismounting {device} from {mountPoint}...")
        result = subprocess.run(["umount", mountPoint], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            logMessage(f"Standard unmount failed, trying lazy unmount for {mountPoint}")
            result = subprocess.run(["umount", "-l", mountPoint], capture_output=True, text=True, timeout=5)
            
        if result.returncode == 0:
            logMessage(f"Successfully dismounted {mountPoint}")
        else:
            logMessage(f"Failed to dismount {mountPoint}: {result.stderr}")
    except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
        logMessage(f"Error dismounting {mountPoint}: {str(e)}")

def dismountVeracryptVolumes():
    try:
        logMessage("Attempting to dismount VeraCrypt volumes...")
        dismountThread = threading.Thread(target=dismountVeracryptTask)
        dismountThread.daemon = True
        dismountThread.start()
        
        dismountThread.join(timeout=veracryptTimeout)
        
        if dismountThread.is_alive():
            logMessage(f"VeraCrypt dismount taking too long (>{veracryptTimeout}s). Proceeding with next actions.")
            return False
        return True
    except Exception as e:
        logMessage(f"Error during VeraCrypt dismount: {str(e)}")
        return False

def dismountVeracryptTask():
    try:
        subprocess.run("veracrypt -d", shell=True, timeout=veracryptTimeout-2)
        logMessage("VeraCrypt volumes dismounted successfully.")
    except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
        logMessage(f"Error in VeraCrypt dismount task: {str(e)}")

def killProcess():
    if not processesToKill:
        return
        
    for process in processesToKill:
        if not process.strip():
            continue
            
        try:
            logMessage(f"Attempting to terminate process: {process}")
            result = subprocess.run(f"pkill -9 {process}", shell=True, capture_output=True, timeout=5)
            if result.returncode != 0:
                logMessage(f"Failed to terminate process: {result.stderr.decode()}")
            else:
                logMessage(f"Process {process} terminated successfully.")
        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logMessage(f"Error terminating process {process}: {str(e)}")

def shutdownSystem():
    try:
        logMessage("Shutdown will run last after all other processes are complete.")
        logMessage(f"Initiating system {shutdownMode} shutdown...")
        
        if shutdownMode == "forced":
            subprocess.run("sudo poweroff -f", shell=True, timeout=10)
        else:
            subprocess.run("sudo shutdown -h now", shell=True, timeout=10)
            
    except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
        logMessage(f"Failed to shutdown system: {str(e)}")

def deleteFiles():
    filePaths = fileToDelete.split("; ")
    for filePath in filePaths:
        if not filePath:
            continue
            
        try:
            absoluteFilePath = os.path.abspath(filePath)
            if os.path.isfile(absoluteFilePath):
                quotedFilePath = f'"{absoluteFilePath}"'
                logMessage(f"Deleting file: {absoluteFilePath}")
                result = subprocess.run(f"rm {quotedFilePath}", shell=True, capture_output=True, timeout=10)
                if result.returncode != 0:
                    logMessage(f"Failed to delete file: {result.stderr.decode()}")
                else:
                    logMessage(f"File deleted successfully: {absoluteFilePath}")
            else:
                logMessage(f"File not found: {absoluteFilePath}")
        except Exception as e:
            logMessage(f"Error deleting file {filePath}: {str(e)}")

def overwriteFiles():
    filePaths = fileToDelete.split("; ")
    for filePath in filePaths:
        if not filePath:
            continue
        
        try:
            absoluteFilePath = os.path.abspath(filePath)
            if os.path.isfile(absoluteFilePath):
                quotedFilePath = f'"{absoluteFilePath}"'
            
                try:
                    fileSizeBytes = os.path.getsize(absoluteFilePath)
                    fileSizeMb = fileSizeBytes / (1024 * 1024)
                    estimatedTime = int(fileSizeMb * shredPasses)
                    timeout = max(30, min(estimatedTime, 3600))
                except:
                    timeout = max(30, shredPasses * 2)
            
                logMessage(f"Shredding file with {shredPasses} passes: {absoluteFilePath} (timeout: {timeout}s)")
            
                shredThread = threading.Thread(
                    target=lambda: subprocess.run(
                        f"shred -zun {shredPasses} {quotedFilePath}", 
                        shell=True, capture_output=True
                    )
                )
                shredThread.daemon = True
                shredThread.start()
            
                shredThread.join(timeout=timeout)
            
                if shredThread.is_alive():
                    logMessage(f"Shredding file {absoluteFilePath} is taking longer than {timeout}s. Continuing with other tasks.")
                else:
                    logMessage(f"File securely shredded: {absoluteFilePath}")
            else:
                logMessage(f"File not found: {absoluteFilePath}")
        except Exception as e:
            logMessage(f"Error overwriting file {filePath}: {str(e)}")

def turnOffScreen():
    logMessage("Turning off screen...")
    methods = [
        "xset dpms force off",
        "vbetool dpms off",
        "xrandr --output $(xrandr | grep ' connected' | head -n 1 | cut -d ' ' -f1) --off"
    ]
    
    for method in methods:
        try:
            subprocess.run(method, shell=True, timeout=5)
            logMessage(f"Screen turned off using: {method}")
            return
        except:
            continue
            
    logMessage("Failed to turn off screen after trying all methods")

def lockComputer():
    logMessage("Locking computer...")
    try:
        subprocess.run("loginctl lock-session", shell=True, timeout=5)
        logMessage("Screen locked")
    except Exception as e:
        logMessage(f"Failed to lock screen: {str(e)}")


def runCustomCommands():
    for command in customCommands:
        if not command:
            continue
            
        try:
            logMessage(f"Executing command: {command}")
            cmdThread = threading.Thread(
                target=lambda: subprocess.run(
                    command, shell=True, capture_output=True
                )
            )
            cmdThread.daemon = True
            cmdThread.start()
            
            cmdThread.join(timeout=30)
            
            if cmdThread.is_alive():
                logMessage(f"Command is taking too long: {command}. Continuing with other tasks.")
            else:
                logMessage(f"Command executed: {command}")
        except Exception as e:
            logMessage(f"Error executing command '{command}': {str(e)}")

def executeTasks():
    global usbMonitoring
    
    shutdownRequired = "Shutdown" in selectedTasks
    
    for task in selectedTasks:
        if not usbMonitoring:
            logMessage("Monitoring stopped. Aborting remaining tasks.")
            return
            
        try:
            if task == "Dismount VeraCrypt Volumes":
                dismountVeracryptVolumes()
            elif task == "Dismount USB Volumes":
                dismountUsbVolumes()
            elif task == "End Process":
                killProcess()
            elif task == "Delete File":
                deleteFiles()
            elif task == "Overwrite File":
                overwriteFiles()
            elif task == "Turn Off Screen":
                turnOffScreen()
            elif task == "Lock Computer":
                lockComputer()
        except Exception as e:
            logMessage(f"Error executing task '{task}': {str(e)}")
    
    try:
        runCustomCommands()
    except Exception as e:
        logMessage(f"Error running custom commands: {str(e)}")
    
    if shutdownRequired:
        shutdownSystem()

def startUsbMonitoring():
    global usbMonitoring, usbMonitorThread
    
    def monitor_usb_events():
        try:
            context = pyudev.Context()
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by(subsystem='usb')
            monitor.filter_by(subsystem='block')
            monitor.start()
            
            for device in iter(monitor.poll, None):
                if not usbMonitoring:
                    break
                    
                if device.action in ['add', 'remove']:
                    if (device.subsystem == 'block' and device.get('ID_BUS') == 'usb') or \
                       (device.subsystem == 'usb' and device.device_type == 'usb_device'):
                        logMessage(f"USB device {device.action}: {device.device_node or device.sys_name}")
                        executeTasks()
                        break
        except Exception as e:
            logMessage(f"Error in pyudev USB monitoring: {str(e)}")
    
    usbMonitoring = True
    usbMonitorThread = threading.Thread(target=monitor_usb_events)
    usbMonitorThread.daemon = True
    usbMonitorThread.start()
    
    updateVolumeCache()

def toggleUsbPause():
    global usbPauseCounter, usbMonitoring
    
    usbPauseCounter += 1
    if usbPauseCounter == 5:
        usbPauseCounter = 0
        usbMonitoring = False
        usbStartButton.config(state=tk.NORMAL)
        usbPauseButton.config(state=tk.DISABLED)

def onUsbStartButtonClick():
    global selectedTasks, customCommands, fileToDelete, processesToKill
    global veracryptTimeout, usbTimeout, shredPasses, shutdownMode, volumesToDismount
    
    selectedTasks = [task.get() for task in tasks if task.get()]
    if not selectedTasks:
        messagebox.showerror("Error", "Please select at least one task")
        return
    
    customCommands = []
    for commandEntry in commandEntries:
        if commandEntry.get().strip():
            customCommands.append(commandEntry.get().strip())
    
    processesToKill = []
    for processEntry in processEntries:
        if processEntry.get().strip():
            processesToKill.append(processEntry.get().strip())
    
    fileToDelete = fileEntry.get()
    
    try:
        veracryptTimeoutValue = int(veracryptTimeoutEntry.get())
        if veracryptTimeoutValue > 0:
            veracryptTimeout = veracryptTimeoutValue
    except ValueError:
        pass
    
    try:
        usbTimeoutValue = int(usbTimeoutEntry.get())
        if usbTimeoutValue > 0:
            usbTimeout = usbTimeoutValue
    except ValueError:
        pass
    
    try:
        shredPassesValue = int(shredPassesEntry.get())
        if shredPassesValue > 0:
            shredPasses = shredPassesValue
    except ValueError:
        pass
    
    shutdownMode = shutdownModeVar.get()
    
    volumesToDismount = volumesEntry.get().split(";")
    volumesToDismount = [vol.strip() for vol in volumesToDismount if vol.strip()]
    
    if usbMonitoring:
        usbStatusLabel.config(text="USB Monitoring started...")
    else:
        startUsbMonitoring()
        usbPauseButton.config(state=tk.NORMAL)
        usbStartButton.config(state=tk.DISABLED)
        usbStatusLabel.config(text="USB Monitoring started...")
        logMessage("USB change monitoring armed and ready.")

def onUsbPauseButtonClick():
    toggleUsbPause()
    if usbMonitoring:
        usbStatusLabel.config(text="USB Monitoring started...")
    else:
        usbStatusLabel.config(text="USB Monitoring paused...")
        if usbPauseCounter == 0:
            logMessage("USB change monitoring disarmed.")

def selectFiles():
    try:
        filePaths = filedialog.askopenfilenames()
        if filePaths:
            fileEntry.delete(0, tk.END)
            fileEntry.insert(0, "; ".join(filePaths))
    except Exception as e:
        messagebox.showerror("Error", f"Failed to select files: {str(e)}")

def selectVolumes():
    try:
        mountedVolumes = getMountedUsbVolumes()
        
        if not mountedVolumes:
            messagebox.showinfo("No Volumes", "No USB volumes currently mounted")
            return
        
        volumeSelect = tk.Toplevel()
        volumeSelect.title("Select USB Volumes")
        volumeSelect.geometry("500x400")
        
        ttk.Label(volumeSelect, text="Select volumes to dismount:").pack(pady=10)
        
        volumeFrame = ttk.Frame(volumeSelect)
        volumeFrame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        volumeVars = []
        for device, mountPoint in mountedVolumes:
            if not isSystemVolume(device, mountPoint):
                var = tk.BooleanVar(value=False)
                volumeVars.append((var, device, mountPoint))
                cb = ttk.Checkbutton(volumeFrame, 
                                    text=f"{device} mounted at {mountPoint}", 
                                    variable=var)
                cb.pack(anchor='w', padx=5, pady=2)
        
        def onSelect():
            selected = []
            for var, device, mountPoint in volumeVars:
                if var.get():
                    selected.append(device)
            
            volumesEntry.delete(0, tk.END)
            volumesEntry.insert(0, "; ".join(selected))
            volumeSelect.destroy()
        
        def selectAll():
            for var, _, _ in volumeVars:
                var.set(True)
        
        def deselectAll():
            for var, _, _ in volumeVars:
                var.set(False)
        
        buttonFrame = ttk.Frame(volumeSelect)
        buttonFrame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(buttonFrame, text="Select All", command=selectAll).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttonFrame, text="Deselect All", command=deselectAll).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttonFrame, text="OK", command=onSelect).pack(side=tk.RIGHT, padx=5)
        ttk.Button(buttonFrame, text="Cancel", command=volumeSelect.destroy).pack(side=tk.RIGHT, padx=5)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to show volume selection: {str(e)}")

def logMessage(message):
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        logText.config(state=tk.NORMAL)
        logText.insert(tk.END, f"[{timestamp}] {message}\n")
        logText.see(tk.END)
        logText.config(state=tk.DISABLED)
    except Exception as e:
        print(f"Error logging message: {str(e)}")

def addProcessEntry():
    try:
        processEntry = ttk.Entry(processEntriesFrame)
        processEntry.pack(fill=tk.X, padx=5, pady=2)
        processEntries.append(processEntry)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to add process entry: {str(e)}")

def addCommandEntry():
    try:
        commandEntry = ttk.Entry(commandEntriesFrame)
        commandEntry.pack(fill=tk.X, padx=5, pady=2)
        commandEntries.append(commandEntry)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to add command entry: {str(e)}")

def onTabChanged(event):
    notebook.focus_set()

def createGui():
    global usbStartButton, usbPauseButton, usbStatusLabel
    global tasks, commandEntries, fileEntry, processEntries
    global logText, veracryptTimeoutEntry, usbTimeoutEntry
    global notebook, processEntriesFrame, commandEntriesFrame
    global shutdownModeVar, volumesEntry, shredPassesEntry

    try:
        root = tk.Tk()
        root.title("USB Killswitch")
        root.geometry("650x750")
        root.configure(bg="#f0f0f0")

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TButton', font=('Arial', 10), background='#4a7abc')
        style.configure('TCheckbutton', font=('Arial', 10), background='#f0f0f0')
        style.configure('TLabel', font=('Arial', 10), background='#f0f0f0')
        style.configure('TNotebook', background='#f0f0f0')
        style.map('TButton', 
            background=[('active', '#5a8adc'), ('disabled', '#cccccc')],
            foreground=[('disabled', '#888888')])

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        notebook.bind("<<NotebookTabChanged>>", onTabChanged)

        mainTab = ttk.Frame(notebook, style='TFrame')
        notebook.add(mainTab, text="Configuration")

        monitoringTab = ttk.Frame(notebook, style='TFrame')
        notebook.add(monitoringTab, text="Monitoring Controls")

        logTab = ttk.Frame(notebook, style='TFrame')
        notebook.add(logTab, text="Logs")
        
        docsTab = ttk.Frame(notebook, style='TFrame')
        notebook.add(docsTab, text="Documentation")

        configFrame = ttk.LabelFrame(mainTab, text="Configuration Settings")
        configFrame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        timeoutFrame = ttk.Frame(configFrame)
        timeoutFrame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(timeoutFrame, text="VeraCrypt Timeout (sec):").pack(side=tk.LEFT)
        veracryptTimeoutEntry = ttk.Entry(timeoutFrame, width=5)
        veracryptTimeoutEntry.insert(0, "30")
        veracryptTimeoutEntry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(timeoutFrame, text="USB Dismount Timeout (sec):").pack(side=tk.LEFT, padx=(10,0))
        usbTimeoutEntry = ttk.Entry(timeoutFrame, width=5)
        usbTimeoutEntry.insert(0, "15")
        usbTimeoutEntry.pack(side=tk.LEFT, padx=5)
        
        shredFrame = ttk.Frame(configFrame)
        shredFrame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(shredFrame, text="Shred Overwrites:").pack(side=tk.LEFT)
        shredPassesEntry = ttk.Entry(shredFrame, width=5)
        shredPassesEntry.insert(0, "10")
        shredPassesEntry.pack(side=tk.LEFT, padx=5)
        
        shutdownFrame = ttk.LabelFrame(configFrame, text="Shutdown Options")
        shutdownFrame.pack(fill=tk.X, padx=10, pady=5)
        
        shutdownModeVar = tk.StringVar(value="immediate")
        ttk.Radiobutton(shutdownFrame, text="Immediate (shutdown -h now)", 
                       variable=shutdownModeVar, value="immediate").pack(anchor='w', padx=5, pady=2)
        ttk.Radiobutton(shutdownFrame, text="Forced (poweroff -f)", 
                       variable=shutdownModeVar, value="forced").pack(anchor='w', padx=5, pady=2)
        
        volumeFrame = ttk.LabelFrame(configFrame, text="USB Volume Dismounting")
        volumeFrame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(volumeFrame, text="Volumes to dismount (leave empty for all non-system USB volumes):").pack(anchor='w', padx=5, pady=2)
        volumeSelectionFrame = ttk.Frame(volumeFrame)
        volumeSelectionFrame.pack(fill=tk.X, padx=5, pady=2)
        volumesEntry = ttk.Entry(volumeSelectionFrame)
        volumesEntry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        volumeButton = ttk.Button(volumeSelectionFrame, text="Select Volumes", command=selectVolumes)
        volumeButton.pack(side=tk.LEFT, padx=5)
        
        taskFrame = ttk.LabelFrame(configFrame, text="Select Tasks to Execute")
        taskFrame.pack(fill=tk.X, padx=10, pady=10)

        tasks = []

        taskGrid = ttk.Frame(taskFrame)
        taskGrid.pack(fill=tk.X, padx=5, pady=5)

        taskDismount = tk.StringVar(value="Dismount VeraCrypt Volumes")
        taskDismountCheckbox = ttk.Checkbutton(taskGrid, text="Dismount VeraCrypt Volumes", 
                                                 variable=taskDismount, onvalue="Dismount VeraCrypt Volumes", offvalue="")
        taskDismountCheckbox.grid(row=0, column=0, sticky='w', padx=5, pady=2)
        tasks.append(taskDismount)
        
        taskDismountUsb = tk.StringVar(value="Dismount USB Volumes")
        taskDismountUsbCheckbox = ttk.Checkbutton(taskGrid, text="Dismount USB Volumes", 
                                                   variable=taskDismountUsb, onvalue="Dismount USB Volumes", offvalue="")
        taskDismountUsbCheckbox.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        tasks.append(taskDismountUsb)

        taskEndProcess = tk.StringVar(value="End Process")
        taskEndProcessCheckbox = ttk.Checkbutton(taskGrid, text="End Process", 
                                                   variable=taskEndProcess, onvalue="End Process", offvalue="")
        taskEndProcessCheckbox.grid(row=1, column=0, sticky='w', padx=5, pady=2)
        tasks.append(taskEndProcess)

        taskDeleteFile = tk.StringVar(value="Delete File")
        taskDeleteFileCheckbox = ttk.Checkbutton(taskGrid, text="Delete File", 
                                                   variable=taskDeleteFile, onvalue="Delete File", offvalue="")
        taskDeleteFileCheckbox.grid(row=1, column=1, sticky='w', padx=5, pady=2)
        tasks.append(taskDeleteFile)

        taskOverwriteFile = tk.StringVar(value="Overwrite File")
        taskOverwriteFileCheckbox = ttk.Checkbutton(taskGrid, text="Overwrite File", 
                                                      variable=taskOverwriteFile, onvalue="Overwrite File", offvalue="")
        taskOverwriteFileCheckbox.grid(row=2, column=0, sticky='w', padx=5, pady=2)
        tasks.append(taskOverwriteFile)

        taskTurnOffScreen = tk.StringVar(value="Turn Off Screen")
        taskTurnOffScreenCheckbox = ttk.Checkbutton(taskGrid, text="Turn Off Screen", 
                                                       variable=taskTurnOffScreen, onvalue="Turn Off Screen", offvalue="")
        taskTurnOffScreenCheckbox.grid(row=2, column=1, sticky='w', padx=5, pady=2)
        tasks.append(taskTurnOffScreen)

        taskLockComputer = tk.StringVar(value="Lock Computer")
        taskLockComputerCheckbox = ttk.Checkbutton(taskGrid, text="Lock Computer", 
                                                     variable=taskLockComputer, onvalue="Lock Computer", offvalue="")
        taskLockComputerCheckbox.grid(row=3, column=0, sticky='w', padx=5, pady=2)
        tasks.append(taskLockComputer)

        taskShutdown = tk.StringVar(value="Shutdown")
        taskShutdownCheckbox = ttk.Checkbutton(taskGrid, text="Shutdown", 
                                                variable=taskShutdown, onvalue="Shutdown", offvalue="")
        taskShutdownCheckbox.grid(row=3, column=1, sticky='w', padx=5, pady=2)
        tasks.append(taskShutdown)

        processFrame = ttk.LabelFrame(configFrame, text="Process Management")
        processFrame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(processFrame, text="Processes to Kill:").pack(anchor='w', padx=5, pady=2)
        
        processEntriesFrame = ttk.Frame(processFrame)
        processEntriesFrame.pack(fill=tk.X, padx=5, pady=2)
        
        processEntries = []
        initialProcessEntry = ttk.Entry(processEntriesFrame)
        initialProcessEntry.pack(fill=tk.X, padx=5, pady=2)
        processEntries.append(initialProcessEntry)
        
        addProcessButton = ttk.Button(processFrame, text="Add More Processes", command=addProcessEntry)
        addProcessButton.pack(anchor='e', padx=5, pady=5)

        fileFrame = ttk.LabelFrame(configFrame, text="File Management")
        fileFrame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(fileFrame, text="Files to Delete/Overwrite:").pack(anchor='w', padx=5, pady=2)
        fileSelectionFrame = ttk.Frame(fileFrame)
        fileSelectionFrame.pack(fill=tk.X, padx=5, pady=2)
        fileEntry = ttk.Entry(fileSelectionFrame)
        fileEntry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        fileButton = ttk.Button(fileSelectionFrame, text="Select Files", command=selectFiles)
        fileButton.pack(side=tk.LEFT, padx=5)

        commandFrame = ttk.LabelFrame(configFrame, text="Custom Commands")
        commandFrame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(commandFrame, text="Commands to Execute:").pack(anchor='w', padx=5, pady=2)
        
        commandEntriesFrame = ttk.Frame(commandFrame)
        commandEntriesFrame.pack(fill=tk.X, padx=5, pady=2)
        
        commandEntries = []
        initialCommandEntry = ttk.Entry(commandEntriesFrame)
        initialCommandEntry.pack(fill=tk.X, padx=5, pady=2)
        commandEntries.append(initialCommandEntry)
        
        addCommandButton = ttk.Button(commandFrame, text="Add More Commands", command=addCommandEntry)
        addCommandButton.pack(anchor='e', padx=5, pady=5)

        monitorFrame = ttk.Frame(monitoringTab)
        monitorFrame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        usbMonitorFrame = ttk.LabelFrame(monitorFrame, text="USB Change Monitoring")
        usbMonitorFrame.pack(fill=tk.X, padx=10, pady=10)
        
        usbButtonFrame = ttk.Frame(usbMonitorFrame)
        usbButtonFrame.pack(fill=tk.X, padx=5, pady=10)
        
        usbStartButton = ttk.Button(usbButtonFrame, text="Arm USB Change Monitor", 
                                     command=onUsbStartButtonClick)
        usbStartButton.pack(side=tk.LEFT, padx=5)
        
        usbPauseButton = ttk.Button(usbButtonFrame, text="Disarm (Press 5 Times)", 
                                      command=onUsbPauseButtonClick, state=tk.DISABLED)
        usbPauseButton.pack(side=tk.LEFT, padx=5)
        
        usbStatusLabel = ttk.Label(usbMonitorFrame, text="Status: Not Armed")
        usbStatusLabel.pack(fill=tk.X, padx=5, pady=5)

        logFrame = ttk.Frame(logTab)
        logFrame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        logTextFrame = ttk.Frame(logFrame)
        logTextFrame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(logTextFrame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        logText = tk.Text(logTextFrame, wrap=tk.WORD, height=30, state=tk.DISABLED, 
                          yscrollcommand=scrollbar.set)
        logText.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar.config(command=logText.yview)
        
        clearLogButton = ttk.Button(logFrame, text="Clear Log", 
                                     command=lambda: [logText.config(state=tk.NORMAL), 
                                                     logText.delete(1.0, tk.END), 
                                                     logText.config(state=tk.DISABLED)])
        clearLogButton.pack(side=tk.RIGHT, padx=5, pady=5)
        
        docsFrame = ttk.Frame(docsTab)
        docsFrame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        docsText = tk.Text(docsFrame, wrap=tk.WORD, height=30, padx=10, pady=10)
        docsText.pack(fill=tk.BOTH, expand=True)
        
        docsContent = """USB Killswitch

OVERVIEW:
This tool monitors for any USB device changes (insertion or removal) 
and automatically executes configured actions. This is useful for those who have their device abruptly seized.

OPTIONS:
- Dismount VeraCrypt Volumes: Dismount of encrypted containers
- Dismount USB Volumes: Safely eject USB storage
- Delete Files: Standard file deletion
- Overwrite Files: Multi-pass shredding
- End Processes: Terminate specified applications (by process name)
- Lock Computer: Lock the desktop session
- Turn Off Screen: Disable display output
- Shutdown System: Complete system shutdown (executed last)
- Custom Commands: Execute arbitrary shell commands with 30-second timeout

REQUIREMENTS:
- Linux operating system
- Python with tkinter and pyudev
- Root/sudo privileges for some commands

OPERATIONAL NOTES:

Starting Monitoring:
- Configure actions in the "Configuration" tab
- Switch to "Monitoring Controls" tab
- Click "Arm USB Change Monitor"
- Status shows "USB Monitoring started..."

Stopping Monitoring:
- Click "Disarm (Press 5 Times)" button 5 times
- Lowers chance of accidental or forced disarming

But I'm nOt a cRiMiNaL, wHy wOuLd I uSe tHiS tOoL?

First off, this tool was never designed with criminals in mind.
This question makes little sense. There are many reasons why the average person might use this tool:
- To protect against attacks such as rubber ducky USBs, O.MG cables, etc.
- Activists in oppressive countries can use this tool to protect the identities of fellow protestors, even if they get caught and their devices are seized.
- Or even just to secure sensitive data if your laptop is grabbed from you.
Just as criminals use encryption, would it be reasonable for me to label you a criminal simply because you use Signal, WhatsApp, or any other end-to-end encrypted messaging app?


Project repository: https://github.com/nthpyrodev/usb-killswitch
"""
        docsText.insert(tk.END, docsContent)
        docsText.config(state=tk.DISABLED)

        logMessage("USB Killswitch Monitor started. Configure and arm to begin monitoring.")

        notebook.focus_set()

        root.mainloop()
    except Exception as e:
        messagebox.showerror("Error", f"Failed to create GUI: {str(e)}")

def launchGuiWithElevatedPrivileges():
    try:
        if os.geteuid() == 0:
            createGui()
        else:
            try:
                subprocess.run(['sudo', sys.executable] + sys.argv)
            except Exception as e:
                messagebox.showwarning("Warning", 
                    f"Some features may require root privileges. Consider running with sudo.\nError: {str(e)}")
                createGui()
    except Exception as e:
        print(f"Error launching application: {str(e)}")
        createGui()

launchGuiWithElevatedPrivileges()
