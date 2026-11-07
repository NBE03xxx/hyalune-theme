// SPDX-License-Identifier: MIT
#ifndef HYALUNE_QT_THEME_STATE_H
#define HYALUNE_QT_THEME_STATE_H

#include <QtCore/QObject>

class HyaluneThemeState : public QObject
{
    Q_OBJECT
public:
    explicit HyaluneThemeState(QObject *parent);
    bool enabled() const { return m_enabled; }

signals:
    void changed();

private slots:
    void setEnabled(bool enabled);
    void refresh();

private:
    bool m_enabled = false;
    quint64 m_generation = 0;
};

HyaluneThemeState &hyaluneThemeState();

#endif
