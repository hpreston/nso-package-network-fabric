# -*- mode: python; python-indent: 4 -*-
"""
pyATS and Genie based tests that can be reused across different services.
"""

def nxos_features_enabled(device, features=[], desired_state="enabled", log=None): 
    """
    Given a device and set of features, verify they are desired state.
    """

    if log: 
        log.info(f"Looking for features {features} on device {device.name}.")

    results = {
        "success": True, 
        "details": [], 
        "error": []
    }

    if device.os != "nxos": 
        results["success"] = False 
        results["error"].append(f"device {device.name} is not an NX-OS device. It's OS is {device.os}.")
        return results
    
    # Lookup feature details from device 
    feature_data = device.parse("show feature")

    # Loop over features to check
    for feature in features: 
        try:
            feature_state = feature_data["feature"][feature]
            # log.info(f"{feature} feature_state={feature_state}")

            # Check if feature is in desired_state
            if feature_state["instance"]["1"]["state"] != desired_state: 
                results["error"].append(f"Feature {feature} is not {desired_state} on device {device.name}.")
        
        except KeyError: 
            results["error"].append(f"Feature {feature} not found on device {device.name}.")

    if len(results["error"]) > 0:
        results["success"] = False

    return results


def vrfs_exist(device, vrfs=[], desired_state=True, log=None): 
    """
    Given a device and set of VRFs, verify they are in the desired state.
    """

    if log: 
        log.info(f"Looking for vrfs {vrfs} on device {device.name}")

    results = {
        "success": True, 
        "details": [], 
        "error": []
    }

    # lookup and learn VRFs on device
    vrf_data = device.learn("vrf")

    # Loop over desired VRFs and check
    for vrf in vrfs: 
        try: 
            vrf_state = vrf_data.info["vrfs"][vrf]
        except KeyError: 
            vrf_state = False 
        
        # Check desired state 
        if desired_state == True and vrf_state == False: 
            results["error"].append(f"VRF {vrf} not found on device {device.name}.")
        elif desired_state == False and vrf_state != False: 
            results["error"].append(f"VRF {vrf} WAS found on device {device.name} (but desired_state was False).")

    if len(results["error"]) > 0:
        results["success"] = False

    return results


def ospf_vrfs_running(device, vrfs=[], desired_state=True, log=None): 
    """
    Given a device and set of VRFs, verify that OSPF is running..
    """

    if log: 
        log.info(f"Looking OSPF state for vrfs {vrfs} on device {device.name}")

    results = {
        "success": True, 
        "details": [], 
        "error": []
    }

    # lookup and learn OSPF on device
    ospf_data = device.learn("ospf")

    if not ospf_data.info["feature_ospf"]: 
        results["error"].append(f"OSPF is NOT running on device {device.name}.")
    else: 
        # Loop over desired VRFs and check
        for vrf in vrfs: 
            try: 
                vrf_ospf_state = ospf_data.info["vrf"][vrf]
            except KeyError: 
                vrf_ospf_state = False 
            
            # Check desired state 
            if desired_state == True and vrf_ospf_state == False: 
                results["error"].append(f"OSPF state for VRF {vrf} not found on device {device.name}.")
            elif desired_state == False and vrf_ospf_state != False: 
                results["error"].append(f"OSPF state for VRF {vrf} WAS found on device {device.name} (but desired_state was False).")

    if len(results["error"]) > 0:
        results["success"] = False

    return results
