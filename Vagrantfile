# -*- mode: ruby -*-
# vi: set ft=ruby :

VAGRANTFILE_API_VERSION = "2"

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|
    config.vm.box = "sjvair/ubuntu-20.04"

    config.ssh.username = "vagrant"

    # Forward a port from the guest to the host, which allows for outside
    # computers to access the VM, whereas host only networking does not.
    config.vm.network "forwarded_port", guest: 8080, host: 8080 #, auto_correct: true # Web
    config.vm.network "forwarded_port", guest: 8000, host: 8000 #, auto_correct: true # Server
    config.vm.network "forwarded_port", guest: 35729, host: 35729 #, auto_correct: true # LiveReload
    # config.vm.network "forwarded_port", guest: 5432, host: 5432, auto_correct: true # Postgres

    # Configure virtual machine specs. Keep it simple, single user.
    config.vm.provider :libvirt do |vm|
        vm.driver = "kvm"
        vm.disk_bus = "virtio"
        vm.memory = 4096
        vm.cpus = 4
    end

    # Config hostname and IP address so entry can be added to HOSTS file
    config.vm.hostname = "camp-vagrant"

    # Configure a synced folder between HOST and GUEST
    config.vm.synced_folder ".", "/vagrant", type: "nfs", nfs_version: 4, id: "camp-server"

    # Kick off a shell script to install dependencies
    config.vm.provision "shell", privileged: true, path: "./vagrant/provision-root.sh"
    config.vm.provision "shell", privileged: false, path: "./vagrant/provision-user.sh"
end
