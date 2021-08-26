# -*- mode: python; python-indent: 4 -*-
"""
Functions used across the different Network Fabric Python modules.
"""

from _ncs import decrypt
import genie.testbed
from pyats.async_ import pcall


def create_testbed(root, testbed_name="testbed", devices=[], log=None):
    """
    Function to create a pyATS Testbed containing a given set of devices.
    """
    
    if log: 
        log.info(f"Creating a pyATS testbed called {testbed_name} from devices {devices}.")

    testbed_data = {
        "testbed": {
            "name": testbed_name, 
        }, 
        "devices": {}
    }

    # Add devices to the testbed
    for device in devices: 
        testbed_data["devices"].update(
            create_pyats_device(
                root=root,
                device_name=device,
                log=log
            )
        )

    # NOTE: Uncomment this line just for dev and debugging. Will print credentials in clear text
    # if log: log.info(f"testbed_data: {testbed_data}")

    # Create testbed from data
    testbed = genie.testbed.load(testbed_data)

    return testbed



def create_pyats_device(root, device_name, log=None): 
    """
    Create a pyATS testbed device from an NSO device_name
    """

    if log: 
        log.info(f'Creating pyATS device definition for device {device_name}')

    device = root.devices.device[device_name]
    auth = root.devices.authgroups.group[device.authgroup].default_map

    # Keys are NSO Platform Names and Values are pyATS OS options
    device_os_map = {
        "ios": "ios", 
        "ios-xe": "iosxe", 
        "NX-OS": "nxos", 
        "ios-xr": "iosxr", 
        "asa": "asa"
    }

    # Default ports for CLI protocols
    connection_port_map = { 
        "ssh": 22, 
        "telnet": 23
    }

    # Determine the protocol and port for the testbed 
    protocol = str(device.device_type.cli.protocol)
    port = device.port if device.port else connection_port_map[protocol] 

    device_data = {
        device_name: {
            "os": device_os_map[device.platform.name], 
            "connections": {
                "default": {
                    "ip": device.address, 
                    "protocol": protocol, 
                    "port": port,
                },
            },
            "credentials": {
                "default": {
                    "username": auth.remote_name, 
                    "password": decrypt(auth.remote_password), 
                }
            }
        }
    }

    return device_data


def testbed_connect(testbed, log_stdout=False, log=None): 
    """
    Connect to devices in a testbed if one is provided
    """
    # Only if a valid testbed was created
    if testbed: 
        if log: log.info(f"Connecting testbed {testbed.name}")
        testbed.connect(learn_hostname=True, log_stdout=log_stdout)


def testbed_connection_status(testbed, log=None): 
    """
    Report the connection status of devices in a testbed.
    """
    # Only if a valid testbed was created
    if testbed and log: 
        # Print connection status
        for device in testbed.devices: 
            log.info(f"Connection status {device}: {testbed.devices[device].connected}")


def testbed_disconnect(testbed, log=None): 
    """
    Disconnect from all devices in a testbed.
    """

    def disconnect(device, log=log): 
        """Function for use with pcall"""

        if log: log.info(f"Disconnecting device {device.name}")
        device.settings.GRACEFUL_DISCONNECT_WAIT_SEC = 0
        device.settings.POST_DISCONNECT_WAIT_SEC = 0
        device.disconnect()
        

    # Only if a valid testbed was created
    if testbed:
        if log: log.info(f"Disconnecting testbed {testbed.name}")

        pcall(disconnect, device=testbed.devices.values())
