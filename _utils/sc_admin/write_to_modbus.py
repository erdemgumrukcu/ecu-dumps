from pymodbus.client import ModbusTcpClient


if __name__ == "__main__":
    modbus_configuration = {}
    modbus_configuration["host"] = "localhost"
    modbus_configuration["port"] = 502
    modbus_configuration["unit_id"] = 1
    modbus_configuration["timeout"] = 60
    modbus_configuration["registers"] = {}
    modbus_configuration["registers"]["p"] = 0
    modbus_configuration["registers"]["q"] = 16
    modbus_configuration["time_offset_seconds"] = 15

    host = modbus_configuration["host"]
    port = modbus_configuration["port"]
    unit_id = modbus_configuration["unit_id"]
    timeout = modbus_configuration["timeout"]
    p_address = modbus_configuration["registers"]["p"]
    q_address = modbus_configuration["registers"]["q"]
    p = 10
    q = 0

    client = ModbusTcpClient(host=host, port=port, timeout=timeout)
    if not client.connect():
        raise ConnectionError(f"Could not connect to Modbus server at {host}:{port}")
    print(f"Connected to Modbus server at {host}:{port}")

    response_p = client.write_register(address=p_address, value=p, device_id=unit_id)
    if response_p.isError():
        print(f"Failed to write p: {response_p}")
    else:
        print(f"Wrote p: {p})")

    response_q = client.write_register(address=q_address, value=q, device_id=unit_id)
    if response_q.isError():
        print(f"Failed to write q: {response_q}")
    else:
        print(f"Wrote q:  {q})")
    client.close()
    print("Modbus connection closed.")