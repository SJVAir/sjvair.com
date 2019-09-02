# -*- mode: ruby -*-
# vi: set ft=ruby :

VAGRANTFILE_API_VERSION = "2"

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|
    config.vm.box = "ubuntu/bionic64"

    config.ssh.username = "vagrant"

    # Forward a port from the guest to the host, which allows for outside
    # computers to access the VM, whereas host only networking does not.
    config.vm.network "forwarded_port", guest: 8080, host: 8080 # Web
    config.vm.network "forwarded_port", guest: 8000, host: 8000 # Server
    config.vm.network "forwarded_port", guest: 35729, host: 35729 # LiveReload
    # config.vm.network "forwarded_port", guest: 5432, host: 5432 # Postgres

    # Configure virtual machine specs. Keep it simple, single user.
    config.vm.provider :virtualbox do |p|
        p.customize ["modifyvm", :id, "--memory", 4096]
        p.customize ["modifyvm", :id, "--cpus", 4]
        p.customize ["modifyvm", :id, "--cpuexecutioncap", 50]
    end

    # Config hostname and IP address so entry can be added to HOSTS file
    config.vm.hostname = "camp-vagrant"

    # Configure a synced folder between HOST and GUEST
    config.vm.synced_folder ".", "/vagrant", id: "camp-server", :mount_options => ["dmode=744","fmode=744"]
    # config.vm.synced_folder "../frontend", "/vagrant/frontend", id: "camp-frontend", :mount_options => ["dmode=744","fmode=744"]

    # Kick off a shell script to install dependencies
    config.vm.provision "shell", privileged: true, path: "./vagrant/provision-root.sh"
    config.vm.provision "shell", privileged: false, path: "./vagrant/provision-user.sh"
end
