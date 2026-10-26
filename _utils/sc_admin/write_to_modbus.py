from pymodbus.client import ModbusTcpClient


if __name__ == "__main__":
    modbus_configuration = {}
    modbus_configuration["host"] = "localhost"
    modbus_configuration["port"] = 502
    modbus_configuration["unit_id"] = 1
    modbus_configuration["timeout"] = 60
    modbus_configuration["registers"] = {}
    modbus_configuration["registers"]["ambient_temp"] = 1
    modbus_configuration["registers"]["load_factor"] = 0
    modbus_configuration["time_offset_seconds"] = 15

    host = modbus_configuration["host"]
    port = modbus_configuration["port"]
    unit_id = modbus_configuration["unit_id"]
    timeout = modbus_configuration["timeout"]
    amb_address = modbus_configuration["registers"]["ambient_temp"]
    load_address = modbus_configuration["registers"]["load_factor"]
    ambt = 25
    load = 80

    client = ModbusTcpClient(host=host, port=port, timeout=timeout)
    if not client.connect():
        raise ConnectionError(f"Could not connect to Modbus server at {host}:{port}")
    print(f"Connected to Modbus server at {host}:{port}")

    response_ambt = client.write_register(address=amb_address, value=ambt, device_id=unit_id)
    if response_ambt.isError():
        print(f"Failed to write ambient temperature: {response_ambt}")
    else:
        print(f"Wrote ambient temperature: {ambt})")

    response_load = client.write_register(address=load_address, value=load, device_id=unit_id)
    if response_load.isError():
        print(f"Failed to write load factor: {response_load}")
    else:
        print(f"Wrote load factor:  {load})")
    client.close()
    print("Modbus connection closed.")