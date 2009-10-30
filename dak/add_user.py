#!/usr/bin/env python

"""
Add a user to to the uid/maintainer/fingerprint table and
add his key to the GPGKeyring

@contact: Debian FTP Master <ftpmaster@debian.org>
@copyright: 2004, 2009  Joerg Jaspert <joerg@ganneff.de>
@license: GNU General Public License version 2 or later
"""

################################################################################
# <elmo> wow, sounds like it'll be a big step up.. configuring dak on a
#        new machine even scares me :)
################################################################################

# You don't want to read this script if you know python.
# I know what I say. I dont know python and I wrote it. So go and read some other stuff.

import commands
import sys
import apt_pkg

from daklib import utils
from daklib.dbconn import DBConn, add_database_user, get_or_set_uid
from daklib.regexes import re_gpg_fingerprint, re_user_address, re_user_mails, re_user_name

################################################################################

Cnf = None
Logger = None

################################################################################

def usage(exit_code=0):
    print """Usage: add-user [OPTION]...
Adds a new user to the dak databases and keyrings

    -k, --key                keyid of the User
    -u, --user               userid of the User
    -c, --create             create a system account for the user
    -h, --help               show this help and exit."""
    sys.exit(exit_code)

################################################################################
# Stolen from userdir-ldap
# Compute a random password using /dev/urandom.
def GenPass():
    # Generate a 10 character random string
    SaltVals = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ/."
    Rand = open("/dev/urandom")
    Password = ""
    for i in range(0,15):
        Password = Password + SaltVals[ord(Rand.read(1)[0]) % len(SaltVals)]
    return Password

# Compute the MD5 crypted version of the given password
def HashPass(Password):
    import crypt
    # Hash it telling glibc to use the MD5 algorithm - if you dont have
    # glibc then just change Salt = "$1$" to Salt = ""
    SaltVals = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/."
    Salt  = "$1$"
    Rand = open("/dev/urandom")
    for x in range(0,10):
        Salt = Salt + SaltVals[ord(Rand.read(1)[0]) % len(SaltVals)]
    Pass = crypt.crypt(Password,Salt)
    if len(Pass) < 14:
        raise "Password Error", "MD5 password hashing failed, not changing the password!"
    return Pass

################################################################################

def createMail(login, passwd, keyid, keyring):
    import GnuPGInterface

    message= """

Additionally there is now an account created for you.

"""
    message+= "\nYour password for the login %s is: %s\n" % (login, passwd)

    gnupg = GnuPGInterface.GnuPG()
    gnupg.options.armor = 1
    gnupg.options.meta_interactive = 0
    gnupg.options.extra_args.append("--no-default-keyring")
    gnupg.options.extra_args.append("--always-trust")
    gnupg.options.extra_args.append("--no-secmem-warning")
    gnupg.options.extra_args.append("--keyring=%s" % keyring)
    gnupg.options.recipients = [keyid]
    proc = gnupg.run(['--encrypt'], create_fhs=['stdin', 'stdout'])
    proc.handles['stdin'].write(message)
    proc.handles['stdin'].close()
    output = proc.handles['stdout'].read()
    proc.handles['stdout'].close()
    proc.wait()
    return output

################################################################################

def main():
    global Cnf
    keyrings = None

    Cnf = utils.get_conf()

    Arguments = [('h',"help","Add-User::Options::Help"),
                 ('c',"create","Add-User::Options::Create"),
                 ('k',"key","Add-User::Options::Key", "HasArg"),
                 ('u',"user","Add-User::Options::User", "HasArg"),
                 ]

    for i in [ "help", "create" ]:
        if not Cnf.has_key("Add-User::Options::%s" % (i)):
            Cnf["Add-User::Options::%s" % (i)] = ""

    apt_pkg.ParseCommandLine(Cnf, Arguments, sys.argv)

    Options = Cnf.SubTree("Add-User::Options")
    if Options["help"]:
        usage()

    session = DBConn().session()

    if not keyrings:
        keyrings = Cnf.ValueList("Dinstall::GPGKeyring")

# Ignore the PGP keyring for download of new keys. Ignore errors, if key is missing it will
# barf with the next commands.
    cmd = "gpg --no-secmem-warning --no-default-keyring %s --recv-keys %s" \
           % (utils.gpg_keyring_args(keyrings), Cnf["Add-User::Options::Key"])
    (result, output) = commands.getstatusoutput(cmd)

    cmd = "gpg --with-colons --no-secmem-warning --no-auto-check-trustdb --no-default-keyring %s --with-fingerprint --list-key %s" \
           % (utils.gpg_keyring_args(keyrings),
              Cnf["Add-User::Options::Key"])
    (result, output) = commands.getstatusoutput(cmd)
    m = re_gpg_fingerprint.search(output)
    if not m:
        print output
        utils.fubar("0x%s: (1) No fingerprint found in gpg output but it returned 0?\n%s" \
                                        % (Cnf["Add-User::Options::Key"], utils.prefix_multi_line_string(output, \
                                                                                                                                                                " [GPG output:] ")))
    primary_key = m.group(1)
    primary_key = primary_key.replace(" ","")

    uid = ""
    if Cnf.has_key("Add-User::Options::User") and Cnf["Add-User::Options::User"]:
        uid = Cnf["Add-User::Options::User"]
        name = Cnf["Add-User::Options::User"]
    else:
        u = re_user_address.search(output)
        if not u:
            print output
            utils.fubar("0x%s: (2) No userid found in gpg output but it returned 0?\n%s" \
                        % (Cnf["Add-User::Options::Key"], utils.prefix_multi_line_string(output, " [GPG output:] ")))
        uid = u.group(1)
        n = re_user_name.search(output)
        name = n.group(1)

# Look for all email addresses on the key.
    emails=[]
    for line in output.split('\n'):
        e = re_user_mails.search(line)
        if not e:
            continue
        emails.append(e.group(2))


    print "0x%s -> %s <%s> -> %s -> %s" % (Cnf["Add-User::Options::Key"], name, emails[0], uid, primary_key)

    prompt = "Add user %s with above data (y/N) ? " % (uid)
    yn = utils.our_raw_input(prompt).lower()

    if yn == "y":
        # Create an account for the user?
        summary = ""
        if Cnf.FindB("Add-User::CreateAccount") or Cnf["Add-User::Options::Create"]:
            password = GenPass()
            pwcrypt = HashPass(password)
            if Cnf.has_key("Add-User::GID"):
                cmd = "sudo /usr/sbin/useradd -g users -m -p '%s' -c '%s' -G %s %s" \
                       % (pwcrypt, name, Cnf["Add-User::GID"], uid)
            else:
                cmd = "sudo /usr/sbin/useradd -g users -m -p '%s' -c '%s' %s" \
                       % (pwcrypt, name, uid)
            (result, output) = commands.getstatusoutput(cmd)
            if (result != 0):
                utils.fubar("Invocation of '%s' failed:\n%s\n" % (cmd, output), result)
            try:
                summary+=createMail(uid, password, Cnf["Add-User::Options::Key"], Cnf["Dinstall::GPGKeyring"])
            except:
                summary=""
                utils.warn("Could not prepare password information for mail, not sending password.")

        # Now add user to the database.
        # Note that we provide a session, so we're responsible for committing
        uidobj = get_or_set_uid(uid, session=session)
        uid_id = uidobj.uid_id
        add_database_user(uid)
        session.commit()

        # The following two are kicked out in rhona, so we don't set them. kelly adds
        # them as soon as she installs a package with unknown ones, so no problems to expect here.
        # Just leave the comment in, to not think about "Why the hell aren't they added" in
        # a year, if we ever touch uma again.
        #          maint_id = database.get_or_set_maintainer_id(name)
        #          session.execute("INSERT INTO fingerprint (fingerprint, uid) VALUES (:fingerprint, uid)",
        #                          {'fingerprint': primary_key, 'uid': uid_id})

        # Lets add user to the email-whitelist file if its configured.
        if Cnf.has_key("Dinstall::MailWhiteList") and Cnf["Dinstall::MailWhiteList"] != "":
            file = utils.open_file(Cnf["Dinstall::MailWhiteList"], "a")
            for mail in emails:
                file.write(mail+'\n')
            file.close()

        print "Added:\nUid:\t %s (ID: %s)\nMaint:\t %s\nFP:\t %s" % (uid, uid_id, \
                     name, primary_key)

        # Should we send mail to the newly added user?
        if Cnf.FindB("Add-User::SendEmail"):
            mail = name + "<" + emails[0] +">"
            Subst = {}
            Subst["__NEW_MAINTAINER__"] = mail
            Subst["__UID__"] = uid
            Subst["__KEYID__"] = Cnf["Add-User::Options::Key"]
            Subst["__PRIMARY_KEY__"] = primary_key
            Subst["__FROM_ADDRESS__"] = Cnf["Dinstall::MyEmailAddress"]
            Subst["__HOSTNAME__"] = Cnf["Dinstall::MyHost"]
            Subst["__SUMMARY__"] = summary
            new_add_message = utils.TemplateSubst(Subst,Cnf["Dir::Templates"]+"/add-user.added")
            utils.send_mail(new_add_message)

    else:
        uid = None

#######################################################################################

if __name__ == '__main__':
    main()
