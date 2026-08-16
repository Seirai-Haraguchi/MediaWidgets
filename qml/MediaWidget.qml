import QtQuick
import QtQuick.Layouts
import RinUI
import ClassWidgets.Theme

Widget {
    id: root
    text: qsTr("Media")

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 2
        Text {
            id: artistText
            Layout.fillWidth: true
            text: ""
            color: "#9AA0A6"
            font.pixelSize: 12
            font.weight: Font.Normal
            elide: Text.ElideRight
            maximumLineCount: 1
        }
        Title {
            id: titleText
            Layout.fillWidth: true
            text: ""
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }
    Binding {
        target: smtcConnections
        property: "target"
        value: backend
    }
    Connections {
        id: smtcConnections
        function onArtistChanged() {
            artistText.text = backend.artist
        }
        function onTitleChanged() {
            titleText.text = backend.title
        }
    }
    onBackendChanged: {
        if (backend) {
            artistText.text = backend.artist
            titleText.text = backend.title
        }
    }
}
