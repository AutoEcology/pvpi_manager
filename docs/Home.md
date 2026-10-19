# PV Pi docs

The PV Pi (PhotoVoltaic Pi) is a Raspberry Pi HAT that powers your Pi from a 12 V lithium iron phosphate (LiFePO4) battery and charges that battery from a solar panel. Its onboard microcontroller handles the off-grid smarts: shutting down on a low battery, waking up again, and keeping time.

pvpi_manager is the Python software that talks to it: a command line tool, a few background services, a web dashboard, and a client you can use in your own code.

- [Getting started](Getting-started.md): set up your Pi and install pvpi_manager
- [Services and dashboard](Services-and-dashboard.md): what runs in the background, and the web dashboard
- [Scheduling](Scheduling.md): choose when your Pi is on
- [Power log](Power-log.md): see when your Pi was on
- [Configuration](Configuration.md): every setting in `config.json`
- [Commands](Commands.md): the `pvpi` command line tool
- [Python client](Python-client.md): use the PV Pi from your own code
- [Troubleshooting](Troubleshooting.md): checking the services and their logs

Need more help? There's the [User Manual](https://static1.squarespace.com/static/6767a8ab1279321b70138597/t/69dae05a35751f0597eea13b/1775951962539/PV_PI_User_Manual.pdf), the [PV Pi tutorials](https://youtube.com/playlist?list=PLbFaSy7wJeFz2h7MJX0VhsMdpvZVvqfuv&si=jxs1IlyUbiJkMmiR) on the AutoEcology YouTube channel, and the [AutoEcology Discord](https://discord.gg/jhXaSxVU9g).

Next: [Getting started](Getting-started.md)
