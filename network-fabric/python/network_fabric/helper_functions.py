# -*- mode: python; python-indent: 4 -*-
"""
Functions used across the different Network Fabric Python modules.
"""

from _ncs import decrypt


def find_layer3_switch_pair(fabric): 
    """Function to locate the Layer 3 enabled switch-pair on a fabric."""

    layer3_pair = None
    for pair in fabric.switch_pair: 
        if pair.layer3: 
            layer3_pair = pair 
    
    return layer3_pair


def test_results_action_output(test_name, result, action_output): 
    """
    Given a test results dictionary, create action outputs for errors.
    """

    # Update action output and results
    if not result["success"]:
        for error in result["error"]: 
            test_error = action_output.error.create()
            test_error.test = test_name
            test_error.message = error


def test_action_overall_status(action_output): 
    """
    Update the overall status of a test action.
    """

    if len(action_output.error) == 0: 
        action_output.message = "Test was successful"
        action_output.success = True
    else: 
        action_output.message = "Errors were encountered during test."
        action_output.success = False
