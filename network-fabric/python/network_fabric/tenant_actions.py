import ncs
from ncs.dp import Action
from _ncs import decrypt
from _ncs.dp import action_set_timeout
from .helper_functions import find_layer3_switch_pair, test_results_action_output, test_action_overall_status
from .pyats_helpers import create_testbed, testbed_connect, testbed_disconnect
from .pyats_helpers import testbed_connection_status
from .pyats_tests import nxos_features_enabled, vrfs_exist, ospf_vrfs_running


class TenantAction(Action): 
    @Action.action
    def cb_action(self, uinfo, name, kp, action_input, action_output, trans):
        self.log.info('TenantAction: ', name)
        test_container = ncs.maagic.get_node(trans, kp)
        service = test_container._parent
        root = ncs.maagic.get_root(trans)
        trans.maapi.install_crypto_keys()

        if name == 'tenant':
            # This test can run longer than the default. Increasing timeout to 6 minutes
            action_set_timeout(uinfo, 360)

            self.tenant_test(service, root, action_input, action_output)

    def tenant_test(self, service, root, action_input, action_output): 

        # Currently all tests related to Layer 3 configuration. If tests are added other than L3 this if condition will need to change.
        if service.layer3.enabled: 
            self.log.info(f'Running tenant_test on network-tenant {service.name}')

            # Setup - Create Testbed for Layer 3 Pair
            self.log.info(f"Setting up pyATS Testbed for network-tenant {service.name}")
            # Find network-fabric and layer3 switch pair 
            fabric = root.network_fabric[service.fabric]
            layer3_pair = find_layer3_switch_pair(fabric)

            testbed = create_testbed(
                root=root,
                testbed_name=f"{service.name}_testbed_layer3pair_{layer3_pair.name}",
                devices=[switch.device for switch in layer3_pair.switch], 
                log=self.log
            )

            # for debuging, print out testbed 
            self.log.info(f"testbed = {testbed}")

            # Setup - Connect to testbed
            testbed_connect(testbed, log=self.log)
            testbed_connection_status(testbed, log=self.log)

            # Tests to run on Tenant
            # Layer 3 - Features Enabled (hsrp, interface-vlan, ospf) - Note: hsrp feature called "hsrp_engine" in show command
            for device in testbed.devices: 
                result = nxos_features_enabled(
                    device=testbed.devices[device], 
                    features=["hsrp_engine", "interface-vlan", "ospf"], 
                    log=self.log,
                )

                # for debuging, print results 
                # self.log.info(f"result: {result}")

                # Update action output and results
                test_results_action_output(
                    test_name="nxos feature enabled", 
                    result=result, 
                    action_output=action_output
                )

            # Layer 3 - VRFs exist for tenant 
            # List of VRFs for the tenant
            vrfs = [f"{service.name}_{vrf}" for vrf in service.layer3.vrf]

            for device in testbed.devices: 
                result = vrfs_exist(
                    device=testbed.devices[device], 
                    vrfs=vrfs, 
                    log=self.log,
                )

                # for debuging, print results 
                # self.log.info(f"result: {result}")

                # Update action output and results
                test_results_action_output(
                    test_name="tenant vrfs exist", 
                    result=result, 
                    action_output=action_output
                )

            # Layer 3 - OSPF process running for VRF 
            for device in testbed.devices: 
                result = ospf_vrfs_running(
                    device=testbed.devices[device], 
                    vrfs=vrfs, 
                    log=self.log,
                )

                # for debuging, print results 
                # self.log.info(f"result: {result}")

                # Update action output and results
                test_results_action_output(
                    test_name="tenant ospf vrfs running", 
                    result=result, 
                    action_output=action_output
                )


            # Cleanup - Disconnect from Testbed
            testbed_disconnect(testbed, log=self.log)
            testbed_connection_status(testbed, log=self.log)

        else: 
            self.log.info(f"network-tenant {service.name} has layer3 disabled. No tests to run.")

        # Set overall action status
        test_action_overall_status(action_output)
        