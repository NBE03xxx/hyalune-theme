// SPDX-License-Identifier: MIT
#include "theme-state.h"

#include <QtCore/QCoreApplication>
#include <QtCore/QPointer>
#include <QtDBus/QDBusConnection>
#include <QtDBus/QDBusMessage>
#include <QtDBus/QDBusPendingCallWatcher>
#include <QtDBus/QDBusPendingReply>
#include <QtDBus/QDBusServiceWatcher>

static const QString service = QStringLiteral("io.github.NBE03xxx.Hyalune.QtAppearance");
static const QString objectPath = QStringLiteral("/io/github/NBE03xxx/Hyalune/QtAppearance");

HyaluneThemeState::HyaluneThemeState(QObject *parent) : QObject(parent)
{
    auto bus = QDBusConnection::sessionBus();
    bus.connect(service, objectPath, service, QStringLiteral("ActiveChanged"),
                this, SLOT(setEnabled(bool)));
    auto watcher = new QDBusServiceWatcher(service, bus,
        QDBusServiceWatcher::WatchForRegistration | QDBusServiceWatcher::WatchForUnregistration, this);
    connect(watcher, &QDBusServiceWatcher::serviceRegistered, this, &HyaluneThemeState::refresh);
    connect(watcher, &QDBusServiceWatcher::serviceUnregistered, this, [this] { setEnabled(false); });
    refresh();
}

void HyaluneThemeState::setEnabled(bool enabled)
{
    ++m_generation;
    if (m_enabled == enabled)
        return;
    m_enabled = enabled;
    emit changed();
}

void HyaluneThemeState::refresh()
{
    const auto generation = ++m_generation;
    auto message = QDBusMessage::createMethodCall(service, objectPath, service, QStringLiteral("IsActive"));
    auto watcher = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 3000), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
        [this, generation](QDBusPendingCallWatcher *finished) {
            QDBusPendingReply<bool> reply = *finished;
            if (generation == m_generation)
                setEnabled(reply.isValid() && reply.value());
            finished->deleteLater();
        });
}

HyaluneThemeState &hyaluneThemeState()
{
    static QPointer<HyaluneThemeState> state;
    if (!state)
        state = new HyaluneThemeState(QCoreApplication::instance());
    return *state;
}
