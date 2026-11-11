data = readtable('D:\OneDrive - Howard Hughes Medical Institute\Documents\perfusion_pyside6_starter\perfusion_app\dist-macos\Data\20261019T145457_protocolTemplate.csv');
time = data.time_ms;
voltage = data.voltage_V;
current = data.current_mA;
plot(time,voltage);
hold on;
plot(time,current);